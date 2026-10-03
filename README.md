# 武器配件与改装系统

## 项目描述

武器配件与改装系统的bug修复项目。核心模块 `weapon/mod_system.py` 存在多个已知bug，需要修复后使测试全部通过。

## 已知问题

- 配件只改显示名不改实际属性
- 槽位无限制可装多个无兼容性检查
- 属性叠加简单加法无优先级
- 无配件冲突检测无协同效果
- 预设只存ID不存等级参数无校验
- 解锁条件写死状态不持久化

## 项目结构

```
├── weapon/mod_system.py       # 核心模块（带bug）
├── tests/test_weapon_mod.py    # 验收测试（红态）
├── pyproject.toml          # 项目配置
└── README.md               # 说明文档
```

## 运行测试

```bash
python -m pytest tests/test_weapon_mod.py -q
```

修复目标：所有 16 个测试全部通过。

## 技术要求

- 纯Python标准库，不引入第三方依赖
- 不修改测试文件
- 保持现有API接口不变
- 修复所有已知bug
