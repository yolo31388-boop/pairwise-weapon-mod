"""
武器配件与改装系统 - 验收测试

运行方式：python -m pytest tests/test_weapon_mod.py -q
共 16 个测试用例
"""
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from weapon.mod_system import (
    Mod,
    ModEffect,
    ModError,
    Weapon,
    WeaponModSystem,
)


def make_mod(mod_id, name, slot, weapon_types, effects=None,
             conflicts=None, unlock=None):
    return Mod(
        mod_id=mod_id,
        name=name,
        slot=slot,
        weapon_types=weapon_types,
        effects=effects or [],
        conflicts=conflicts or [],
        unlock=unlock or {},
    )


class TestWeaponModSystem:
    """武器配件与改装系统测试套件"""

    def setup_method(self):
        """每个测试前的初始化：独立存档路径 + 标准武器/配件库"""
        self._tmpdir = tempfile.mkdtemp()
        self.save_path = os.path.join(self._tmpdir, "save.json")
        self.system = WeaponModSystem(config={"save_path": self.save_path})
        self._register_weapons()
        self._register_mods()

    def teardown_method(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _register_weapons(self):
        s = self.system
        s.register_weapon(Weapon("ak", "AK步枪", "rifle", {
            "damage": 40.0, "range": 300.0, "reload_speed": 1.0,
            "accuracy": 50.0, "stability": 60.0, "mobility": 70.0,
            "stealth": 0.0, "zoom": 1.0,
        }))
        s.register_weapon(Weapon("ak_clone", "AK步枪(同型)", "rifle", {
            "damage": 40.0, "range": 300.0, "reload_speed": 1.0,
            "accuracy": 50.0, "stability": 60.0, "mobility": 70.0,
            "stealth": 0.0, "zoom": 1.0,
        }))
        s.register_weapon(Weapon("pistol", "手枪", "pistol", {
            "damage": 20.0, "range": 50.0, "reload_speed": 1.2,
        }))
        s.register_weapon(Weapon("smg", "冲锋枪", "smg", {
            "damage": 25.0, "range": 100.0, "reload_speed": 1.5,
        }))

    def _register_mods(self):
        s = self.system
        s.register_mod(make_mod(
            "quick_mag", "快速弹匣", "magazine", ["rifle", "smg", "pistol"],
            effects=[ModEffect("reload_speed", "pct", 0.3)]))
        s.register_mod(make_mod(
            "long_barrel", "长枪管", "barrel", ["rifle", "smg"],
            effects=[ModEffect("range", "add", 50.0)]))
        s.register_mod(make_mod(
            "sniper_barrel", "狙击枪管", "barrel", ["sniper"],
            effects=[ModEffect("range", "add", 200.0)]))
        s.register_mod(make_mod(
            "shotgun_mag", "霰弹弹匣", "magazine", ["shotgun"],
            effects=[ModEffect("damage", "pct", 0.2)]))
        s.register_mod(make_mod(
            "red_dot", "红点瞄准镜", "optic", ["rifle", "smg", "pistol"],
            effects=[ModEffect("accuracy", "add", 5.0)]))
        s.register_mod(make_mod(
            "scope_4x", "四倍镜", "optic", ["rifle", "sniper"],
            effects=[ModEffect("zoom", "mult", 4.0),
                     ModEffect("accuracy", "add", 10.0)]))
        s.register_mod(make_mod(
            "heavy_stock", "重型枪托", "stock", ["rifle"],
            effects=[ModEffect("stability", "add", 20.0),
                     ModEffect("mobility", "add", -10.0)],
            conflicts=["light_stock"]))
        s.register_mod(make_mod(
            "light_stock", "轻型枪托", "stock", ["rifle"],
            effects=[ModEffect("mobility", "add", 15.0)],
            conflicts=["heavy_stock"]))
        s.register_mod(make_mod(
            "suppressor", "消音器", "muzzle", ["rifle", "smg", "pistol"],
            effects=[ModEffect("damage", "pct", -0.05),
                     ModEffect("stealth", "add", 20.0)]))
        s.register_mod(make_mod(
            "subsonic_ammo", "亚音速弹", "ammo", ["rifle", "smg", "pistol"],
            effects=[ModEffect("damage", "pct", -0.1)]))
        s.register_synergy("suppressor", "subsonic_ammo", [
            ModEffect("stealth", "add", 15.0),
            ModEffect("damage", "pct", 0.05),
        ])
        s.register_mod(make_mod(
            "gold_scope", "黄金瞄准镜", "optic", ["rifle"],
            effects=[ModEffect("accuracy", "add", 20.0)],
            unlock={"player_level": 10, "weapon_level": 5}))

    # ------------------------------------------------------------------
    # 1. 配件应用实际修改属性
    # ------------------------------------------------------------------
    def test_case_01(self):
        """快速弹匣实际加快换弹速度（按基础值百分比）"""
        assert self.system.apply_mod("ak", "quick_mag") is True
        stats = self.system.stat_calculation("ak")
        assert stats["reload_speed"] == pytest.approx(1.0 * 1.3)

    def test_case_02(self):
        """不同配件类型修改对应属性：长枪管加射程、红点加精度"""
        self.system.apply_mod("ak", "long_barrel")
        self.system.apply_mod("ak", "red_dot")
        stats = self.system.stat_calculation("ak")
        assert stats["range"] == pytest.approx(350.0)
        assert stats["accuracy"] == pytest.approx(55.0)
        # 未涉及的属性保持基础值
        assert stats["damage"] == pytest.approx(40.0)

    # ------------------------------------------------------------------
    # 2. 槽位校验
    # ------------------------------------------------------------------
    def test_case_03(self):
        """同一槽位只能装一个配件：红点和四倍镜不能同时装"""
        assert self.system.apply_mod("ak", "red_dot") is True
        assert self.system.apply_mod("ak", "scope_4x") is False
        ok, reason = self.system.slot_validation("ak", "scope_4x")
        assert ok is False and reason == "slot_occupied"
        equipped = self.system.get_equipped_mods("ak")
        assert equipped["optic"]["mod_id"] == "red_dot"
        stats = self.system.stat_calculation("ak")
        assert stats["zoom"] == pytest.approx(1.0)  # 四倍镜未生效

    def test_case_04(self):
        """兼容性检查：手枪装不了狙击枪管，冲锋枪装不了霰弹弹匣"""
        assert self.system.apply_mod("pistol", "sniper_barrel") is False
        ok, reason = self.system.slot_validation("pistol", "sniper_barrel")
        assert ok is False and reason == "incompatible_weapon_type"
        assert self.system.apply_mod("smg", "shotgun_mag") is False
        # 兼容的则可以装
        assert self.system.apply_mod("smg", "quick_mag") is True

    # ------------------------------------------------------------------
    # 3. 属性计算：加法/百分比/乘法 + 固定优先级
    # ------------------------------------------------------------------
    def test_case_05(self):
        """加法 -> 基础值百分比 -> 乘法 的固定优先级"""
        s = self.system
        s.register_mod(make_mod(
            "dmg_barrel", "伤害枪管", "barrel", ["rifle"],
            effects=[ModEffect("damage", "add", 10.0)]))
        s.register_mod(make_mod(
            "dmg_ammo", "伤害弹", "ammo", ["rifle"],
            effects=[ModEffect("damage", "pct", 0.25)]))
        s.register_mod(make_mod(
            "dmg_optic", "伤害镜", "optic", ["rifle"],
            effects=[ModEffect("damage", "mult", 1.5)]))
        s.apply_mod("ak", "dmg_barrel")
        s.apply_mod("ak", "dmg_ammo")
        s.apply_mod("ak", "dmg_optic")
        # (40 + 10 + 40*0.25) * 1.5 = 90
        assert s.stat_calculation("ak")["damage"] == pytest.approx(90.0)

    def test_case_06(self):
        """属性计算与装备顺序无关：同一把枪不同顺序改装结果一致"""
        s = self.system
        s.apply_mod("ak", "heavy_stock")
        s.apply_mod("ak", "long_barrel")
        s.apply_mod("ak", "quick_mag")
        s.apply_mod("ak_clone", "quick_mag")
        s.apply_mod("ak_clone", "long_barrel")
        s.apply_mod("ak_clone", "heavy_stock")
        assert s.stat_calculation("ak") == s.stat_calculation("ak_clone")

    # ------------------------------------------------------------------
    # 4. 冲突检测与协同效果
    # ------------------------------------------------------------------
    def test_case_07(self):
        """互斥配件：重型枪托和轻型枪托不能同时装"""
        s = self.system
        assert s.mod_conflict("heavy_stock", "light_stock") is True
        assert s.mod_conflict("light_stock", "heavy_stock") is True
        assert s.mod_conflict("heavy_stock", "red_dot") is False
        assert s.apply_mod("ak", "heavy_stock") is True
        assert s.apply_mod("ak", "light_stock") is False
        stats = s.stat_calculation("ak")
        assert stats["stability"] == pytest.approx(80.0)
        assert stats["mobility"] == pytest.approx(60.0)  # 轻型枪托未生效

    def test_case_08(self):
        """协同效果：消音器 + 亚音速弹获得额外加成"""
        s = self.system
        s.apply_mod("ak", "suppressor")
        s.apply_mod("ak", "subsonic_ammo")
        stats = s.stat_calculation("ak")
        # 潜行：0 + 20(消音器) + 15(协同) = 35
        assert stats["stealth"] == pytest.approx(35.0)
        # 伤害：40 * (1 - 0.05 - 0.1 + 0.05协同) = 36
        assert stats["damage"] == pytest.approx(36.0)

    # ------------------------------------------------------------------
    # 5. 预设管理
    # ------------------------------------------------------------------
    def test_case_09(self):
        """预设保存完整状态：配件等级和自定义参数不丢失"""
        s = self.system
        s.apply_mod("ak", "quick_mag", level=3, params={"reload_speed": 0.5})
        boosted = s.stat_calculation("ak")["reload_speed"]
        # 自定义参数覆盖效果值：1.0 + 1.0 * 0.5 * 3 = 2.5
        assert boosted == pytest.approx(2.5)
        s.save_preset("我的配置", "ak")
        s.remove_mod("ak", "quick_mag")
        assert s.stat_calculation("ak")["reload_speed"] == pytest.approx(1.0)
        s.load_preset("我的配置", "ak")
        equipped = s.get_equipped_mods("ak")
        assert equipped["magazine"]["level"] == 3
        assert equipped["magazine"]["params"] == {"reload_speed": 0.5}
        assert s.stat_calculation("ak")["reload_speed"] == pytest.approx(boosted)

    def test_case_10(self):
        """预设校验：加载包含已删除配件的预设不崩溃，武器状态不变"""
        s = self.system
        s.apply_mod("ak", "quick_mag")
        s.save_preset("p1", "ak")
        # 模拟重启后该配件已从游戏中删除
        s2 = WeaponModSystem(config={"save_path": self.save_path})
        s2.register_weapon(Weapon("ak", "AK步枪", "rifle", {"reload_speed": 1.0}))
        with pytest.raises(ModError):
            s2.load_preset("p1", "ak")
        assert s2.get_equipped_mods("ak") == {}

    def test_case_11(self):
        """预设兼容性校验：步枪预设不能加载到手枪上，且不会产生部分修改"""
        s = self.system
        s.apply_mod("ak", "long_barrel")
        s.save_preset("rifle_preset", "ak")
        with pytest.raises(ModError):
            s.load_preset("rifle_preset", "pistol")
        assert s.get_equipped_mods("pistol") == {}

    # ------------------------------------------------------------------
    # 6. 配件解锁
    # ------------------------------------------------------------------
    def test_case_12(self):
        """解锁条件可配置：需满足玩家等级和武器等级"""
        s = self.system
        assert s.is_unlocked("gold_scope") is False
        assert s.mod_unlock("gold_scope", player_level=3, weapon_level=1) is False
        assert s.is_unlocked("gold_scope") is False
        assert s.mod_unlock("gold_scope", player_level=10, weapon_level=5) is True
        assert s.is_unlocked("gold_scope") is True
        # 无条件配件默认解锁
        assert s.is_unlocked("quick_mag") is True

    def test_case_13(self):
        """解锁状态持久化：重启（新实例）后配件保持解锁"""
        s = self.system
        assert s.mod_unlock("gold_scope", player_level=10, weapon_level=5) is True
        s2 = WeaponModSystem(config={"save_path": self.save_path})
        s2.register_mod(self.system.mods["gold_scope"])
        assert s2.is_unlocked("gold_scope") is True
        # 锁定的配件无法装备
        s3 = WeaponModSystem(config={"save_path": os.path.join(self._tmpdir, "other.json")})
        self._register_into(s3)
        assert s3.apply_mod("ak", "gold_scope") is False

    def _register_into(self, system):
        """把标准武器/配件注册到指定系统实例"""
        saved = self.system
        self.system = system
        try:
            self._register_weapons()
            self._register_mods()
        finally:
            self.system = saved

    # ------------------------------------------------------------------
    # 综合行为
    # ------------------------------------------------------------------
    def test_case_14(self):
        """卸下配件后属性恢复基础值；显示名称反映已装配件"""
        s = self.system
        s.apply_mod("ak", "long_barrel")
        s.apply_mod("ak", "red_dot")
        assert s.get_display_name("ak") == "AK步枪 [长枪管 + 红点瞄准镜]"
        assert s.remove_mod("ak", "long_barrel") is True
        stats = s.stat_calculation("ak")
        assert stats["range"] == pytest.approx(300.0)
        assert stats["accuracy"] == pytest.approx(55.0)
        assert s.remove_mod("ak", "long_barrel") is False

    def test_case_15(self):
        """预设随存档持久化：新实例可直接加载旧预设"""
        s = self.system
        s.apply_mod("ak", "heavy_stock")
        s.apply_mod("ak", "quick_mag", level=2)
        s.save_preset("persisted", "ak")
        s2 = WeaponModSystem(config={"save_path": self.save_path})
        self._register_into(s2)
        s2.load_preset("persisted", "ak")
        equipped = s2.get_equipped_mods("ak")
        assert equipped["stock"]["mod_id"] == "heavy_stock"
        assert equipped["magazine"]["level"] == 2
        assert s2.stat_calculation("ak") == s.stat_calculation("ak")

    def test_case_16(self):
        """reset 清空全部状态并同步存档；未知ID抛 ModError"""
        s = self.system
        s.apply_mod("ak", "quick_mag")
        s.save_preset("p", "ak")
        s.mod_unlock("gold_scope", player_level=10, weapon_level=5)
        s.reset()
        assert s.get_equipped_mods("ak") == {}
        assert s.is_unlocked("gold_scope") is False
        with pytest.raises(ModError):
            s.load_preset("p", "ak")
        with pytest.raises(ModError):
            s.apply_mod("ak", "nonexistent_mod")
        with pytest.raises(ModError):
            s.stat_calculation("nonexistent_weapon")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
