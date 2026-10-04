"""
武器配件与改装系统 - 核心模块

功能：
- 配件应用实际修改武器属性（按配件类型生效）
- 槽位校验：单槽位单配件 + 武器类型兼容性检查
- 属性计算：加法 / 基础值百分比 / 乘法，固定优先级，结果确定
- 配件冲突检测与协同效果
- 预设管理：保存完整状态（等级+自定义参数），加载前校验
- 配件解锁：条件可配置（玩家等级/武器等级），状态持久化
"""
import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


class ModError(Exception):
    """配件系统错误（未知ID、预设校验失败等）"""


@dataclass
class Config:
    """配置项"""
    save_path: str = "mod_system_save.json"


@dataclass
class ModEffect:
    """单条属性修正。op: 'add' 加法 | 'pct' 基础值百分比 | 'mult' 乘法"""
    stat: str
    op: str
    value: float


@dataclass
class Mod:
    """配件定义"""
    mod_id: str
    name: str
    slot: str
    weapon_types: List[str]
    effects: List[ModEffect] = field(default_factory=list)
    conflicts: List[str] = field(default_factory=list)
    unlock: Dict = field(default_factory=dict)  # {'player_level': n, 'weapon_level': n}


@dataclass
class Weapon:
    """武器定义"""
    weapon_id: str
    name: str
    weapon_type: str
    base_stats: Dict[str, float]
    level: int = 1


# 属性计算固定优先级：先加法，再基础值百分比，最后乘法
_EFFECT_PRIORITY = ("add", "pct", "mult")


class WeaponModSystem:
    """武器配件与改装系统核心类"""

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self._state = {}
        self._history = []
        self.weapons: Dict[str, Weapon] = {}
        self.mods: Dict[str, Mod] = {}
        # weapon_id -> {slot: {'mod_id', 'level', 'params'}}
        self._equipped: Dict[str, Dict[str, Dict]] = {}
        # frozenset({mod_a, mod_b}) -> [ModEffect] 协同加成
        self._synergies: Dict[frozenset, List[ModEffect]] = {}
        self._presets: Dict[str, Dict] = {}
        self._unlocked = set()
        self._save_path = self.config.get("save_path", Config().save_path)
        self._load_state()

    # ------------------------------------------------------------------
    # 基础接口
    # ------------------------------------------------------------------
    def update(self, dt: float):
        """每帧更新"""
        pass

    def reset(self):
        """重置状态（含配件、预设、解锁），并同步持久化"""
        self._state = {}
        self._history = []
        self._equipped = {wid: {} for wid in self.weapons}
        self._presets = {}
        self._unlocked = set()
        self._save_state()

    # ------------------------------------------------------------------
    # 注册
    # ------------------------------------------------------------------
    def register_weapon(self, weapon: Weapon):
        self.weapons[weapon.weapon_id] = weapon
        self._equipped.setdefault(weapon.weapon_id, {})

    def register_mod(self, mod: Mod):
        self.mods[mod.mod_id] = mod

    def register_synergy(self, mod_id_a: str, mod_id_b: str, effects: List[ModEffect]):
        """注册协同效果：两个配件同时装备时额外生效"""
        self._synergies[frozenset((mod_id_a, mod_id_b))] = list(effects)

    # ------------------------------------------------------------------
    # 槽位校验 / 冲突检测
    # ------------------------------------------------------------------
    def slot_validation(self, weapon_id: str, mod_id: str) -> Tuple[bool, str]:
        """校验配件能否装上武器：槽位唯一 + 武器类型兼容"""
        weapon = self.weapons.get(weapon_id)
        mod = self.mods.get(mod_id)
        if weapon is None:
            return False, "weapon_not_found"
        if mod is None:
            return False, "mod_not_found"
        if weapon.weapon_type not in mod.weapon_types:
            return False, "incompatible_weapon_type"
        if mod.slot in self._equipped.get(weapon_id, {}):
            return False, "slot_occupied"
        return True, "ok"

    def mod_conflict(self, mod_id_a: str, mod_id_b: str) -> bool:
        """检测两个配件是否互斥（双向检查）"""
        a = self.mods.get(mod_id_a)
        b = self.mods.get(mod_id_b)
        if a is None or b is None:
            return False
        return mod_id_b in a.conflicts or mod_id_a in b.conflicts

    def _has_conflict_with_equipped(self, weapon_id: str, mod_id: str) -> bool:
        for entry in self._equipped.get(weapon_id, {}).values():
            if self.mod_conflict(entry["mod_id"], mod_id):
                return True
        return False

    # ------------------------------------------------------------------
    # 配件应用 / 移除
    # ------------------------------------------------------------------
    def apply_mod(self, weapon_id: str, mod_id: str,
                  level: int = 1, params: Optional[Dict] = None) -> bool:
        """装配配件。校验失败返回 False，未知ID抛 ModError"""
        if weapon_id not in self.weapons:
            raise ModError(f"未知武器: {weapon_id}")
        if mod_id not in self.mods:
            raise ModError(f"未知配件: {mod_id}")
        ok, reason = self.slot_validation(weapon_id, mod_id)
        if not ok:
            self._history.append(("apply_rejected", weapon_id, mod_id, reason))
            return False
        if not self.is_unlocked(mod_id):
            self._history.append(("apply_rejected", weapon_id, mod_id, "locked"))
            return False
        if self._has_conflict_with_equipped(weapon_id, mod_id):
            self._history.append(("apply_rejected", weapon_id, mod_id, "conflict"))
            return False
        mod = self.mods[mod_id]
        self._equipped[weapon_id][mod.slot] = {
            "mod_id": mod_id,
            "level": level,
            "params": dict(params or {}),
        }
        self._history.append(("apply", weapon_id, mod_id, level))
        return True

    def remove_mod(self, weapon_id: str, mod_id: str) -> bool:
        """卸下配件，属性随之恢复"""
        if weapon_id not in self.weapons:
            raise ModError(f"未知武器: {weapon_id}")
        for slot, entry in self._equipped.get(weapon_id, {}).items():
            if entry["mod_id"] == mod_id:
                del self._equipped[weapon_id][slot]
                self._history.append(("remove", weapon_id, mod_id))
                return True
        return False

    def get_equipped_mods(self, weapon_id: str) -> Dict[str, Dict]:
        """返回 {slot: {'mod_id', 'level', 'params'}} 的副本"""
        if weapon_id not in self.weapons:
            raise ModError(f"未知武器: {weapon_id}")
        return {slot: dict(entry) for slot, entry in self._equipped[weapon_id].items()}

    def get_display_name(self, weapon_id: str) -> str:
        """显示名称 = 武器名 + 已装配件名"""
        if weapon_id not in self.weapons:
            raise ModError(f"未知武器: {weapon_id}")
        weapon = self.weapons[weapon_id]
        names = [self.mods[e["mod_id"]].name
                 for _, e in sorted(self._equipped[weapon_id].items())]
        if not names:
            return weapon.name
        return "{} [{}]".format(weapon.name, " + ".join(names))

    # ------------------------------------------------------------------
    # 属性计算
    # ------------------------------------------------------------------
    def _collect_effects(self, weapon_id: str) -> List[ModEffect]:
        """收集已装配件的全部效果（按槽位排序保证确定性），含协同加成"""
        effects: List[ModEffect] = []
        equipped = self._equipped.get(weapon_id, {})
        for slot in sorted(equipped):
            entry = equipped[slot]
            mod = self.mods[entry["mod_id"]]
            for eff in mod.effects:
                # 自定义参数可按属性名覆盖效果数值
                value = entry["params"].get(eff.stat, eff.value)
                # 加法/百分比效果随配件等级线性放大
                if eff.op in ("add", "pct"):
                    value = value * entry["level"]
                effects.append(ModEffect(eff.stat, eff.op, value))
        equipped_ids = {e["mod_id"] for e in equipped.values()}
        for pair, bonus in self._synergies.items():
            if pair <= equipped_ids:
                effects.extend(bonus)
        return effects

    def stat_calculation(self, weapon_id: str) -> Dict[str, float]:
        """计算武器最终属性。

        固定优先级：add（加法）-> pct（基础值百分比）-> mult（乘法），
        与配件装备顺序无关，结果确定。
        """
        if weapon_id not in self.weapons:
            raise ModError(f"未知武器: {weapon_id}")
        base = self.weapons[weapon_id].base_stats
        stats = dict(base)
        effects = self._collect_effects(weapon_id)
        for op in _EFFECT_PRIORITY:
            for eff in effects:
                if eff.op != op:
                    continue
                if op == "add":
                    stats[eff.stat] = stats.get(eff.stat, 0.0) + eff.value
                elif op == "pct":
                    stats[eff.stat] = stats.get(eff.stat, 0.0) + base.get(eff.stat, 0.0) * eff.value
                else:  # mult
                    stats[eff.stat] = stats.get(eff.stat, 0.0) * eff.value
        return stats

    # ------------------------------------------------------------------
    # 预设管理
    # ------------------------------------------------------------------
    def save_preset(self, name: str, weapon_id: str) -> bool:
        """保存预设：完整记录每个配件的ID、槽位、等级和自定义参数"""
        if weapon_id not in self.weapons:
            raise ModError(f"未知武器: {weapon_id}")
        weapon = self.weapons[weapon_id]
        mods = []
        for slot in sorted(self._equipped[weapon_id]):
            entry = self._equipped[weapon_id][slot]
            mods.append({
                "slot": slot,
                "mod_id": entry["mod_id"],
                "level": entry["level"],
                "params": dict(entry["params"]),
            })
        self._presets[name] = {"weapon_type": weapon.weapon_type, "mods": mods}
        self._save_state()
        self._history.append(("save_preset", name, weapon_id))
        return True

    def load_preset(self, name: str, weapon_id: str) -> bool:
        """加载预设。先整体校验（存在性/兼容性/槽位/互斥），失败抛 ModError，
        校验通过后才应用，武器状态不会被部分修改。"""
        if name not in self._presets:
            raise ModError(f"预设不存在: {name}")
        if weapon_id not in self.weapons:
            raise ModError(f"未知武器: {weapon_id}")
        preset = self._presets[name]
        weapon = self.weapons[weapon_id]
        entries = preset.get("mods", [])

        missing = [m["mod_id"] for m in entries if m["mod_id"] not in self.mods]
        if missing:
            raise ModError(f"预设包含已删除的配件: {missing}")

        seen_slots = set()
        for m in entries:
            mod = self.mods[m["mod_id"]]
            if weapon.weapon_type not in mod.weapon_types:
                raise ModError(f"配件 {m['mod_id']} 与武器类型 {weapon.weapon_type} 不兼容")
            if mod.slot in seen_slots:
                raise ModError(f"预设槽位冲突: {mod.slot}")
            seen_slots.add(mod.slot)

        ids = [m["mod_id"] for m in entries]
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                if self.mod_conflict(ids[i], ids[j]):
                    raise ModError(f"预设配件互斥: {ids[i]} vs {ids[j]}")

        self._equipped[weapon_id] = {}
        for m in entries:
            mod = self.mods[m["mod_id"]]
            self._equipped[weapon_id][mod.slot] = {
                "mod_id": m["mod_id"],
                "level": m.get("level", 1),
                "params": dict(m.get("params", {})),
            }
        self._history.append(("load_preset", name, weapon_id))
        return True

    def get_preset(self, name: str) -> Dict:
        """返回预设内容副本"""
        if name not in self._presets:
            raise ModError(f"预设不存在: {name}")
        return json.loads(json.dumps(self._presets[name]))

    # ------------------------------------------------------------------
    # 配件解锁
    # ------------------------------------------------------------------
    def mod_unlock(self, mod_id: str, player_level: int = 0, weapon_level: int = 0) -> bool:
        """按可配置条件（玩家等级/武器等级）解锁配件，成功则持久化"""
        if mod_id not in self.mods:
            raise ModError(f"未知配件: {mod_id}")
        cond = self.mods[mod_id].unlock or {}
        ok = (player_level >= cond.get("player_level", 0)
              and weapon_level >= cond.get("weapon_level", 0))
        if ok:
            self._unlocked.add(mod_id)
            self._save_state()
            self._history.append(("unlock", mod_id))
        return ok

    def is_unlocked(self, mod_id: str, player_level: int = 0, weapon_level: int = 0) -> bool:
        """查询配件是否已解锁（含持久化状态与等级条件判定）"""
        if mod_id in self._unlocked:
            return True
        mod = self.mods.get(mod_id)
        if mod is None:
            return False
        cond = mod.unlock or {}
        if not cond:
            return True
        return (player_level >= cond.get("player_level", 0)
                and weapon_level >= cond.get("weapon_level", 0))

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------
    def _save_state(self):
        data = {
            "unlocked": sorted(self._unlocked),
            "presets": self._presets,
        }
        try:
            with open(self._save_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    def _load_state(self):
        if not os.path.exists(self._save_path):
            return
        try:
            with open(self._save_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return
        self._unlocked = set(data.get("unlocked", []))
        self._presets = data.get("presets", {})
