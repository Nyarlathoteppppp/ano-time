# AnoTime 开发管理

本目录只记录工程决策、实施计划、验收结果与已知风险；不存放用户 API Key、运行日志、课堂文本或私人课程资料。

## 当前工作流

```text
先写计划
→ 明确不变式与验收项
→ 小批次实现
→ 单元 / 集成测试
→ macOS 实机测试
→ 单独提交
→ 更新本目录中的状态
```

## 文档索引

| 文档 | 用途 | 状态 |
| --- | --- | --- |
| [PYQT_TO_PYSIDE6_MIGRATION_PLAN.md](./PYQT_TO_PYSIDE6_MIGRATION_PLAN.md) | PyQt6 → PySide6 许可与迁移计划 | 规划完成，未开始改代码 |
| [PYSIDE6_TARGET_ARCHITECTURE.md](./PYSIDE6_TARGET_ARCHITECTURE.md) | 单一 Qt binding、UI / Pipeline 边界和迁移 worktree 规则 | 规划完成，未开始改代码 |
| [DECISIONS.md](./DECISIONS.md) | 需要长期遵守的技术与产品决策 | 持续维护 |
| [CHANGELOG.md](./CHANGELOG.md) | 面向后续开发 Agent 的近期变更摘要 | 持续维护 |

## 现有全局文档

- [产品与 Mac 发布路线](../PRODUCT_RELEASE_AND_APP_STORE_ROADMAP.md)
- [重构安全网与不变式](../REFACTORING_SAFETY_NET.md)
- [延迟基准](../LATENCY_BASELINE.md)
- [Agent 交接说明](../AGENT_HANDOFF.md)

## 强制边界

- 不为整理代码而改变 Apple 草稿、ASR、模型路由、字幕节奏或上下文策略。
- 每一批 UI/绑定迁移都必须通过全量测试，并做对应 macOS 实机验证。
- 本机 `config.ini`、Keychain、`transcripts/`、`logs/` 不进入 Git；发布前运行 `python3 tools/release_audit.py .`。
- UI 视觉素材日后必须替换为拥有对外/商业分发权的资源；当前动漫角色素材不属于发布资产。
