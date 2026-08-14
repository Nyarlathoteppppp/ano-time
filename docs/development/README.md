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
| [MAINTENANCE_PROTOCOL.md](./MAINTENANCE_PROTOCOL.md) | 每次开发的记录、验证与交接规范 | 持续维护 |
| [GITHUB_WORKFLOW.md](./GITHUB_WORKFLOW.md) | Branch、Issue、PR、Actions、Release 与实机验收的 GitHub 管理基线 | 本地文件已就绪；等待远端管理员设置 |
| [PYQT_TO_PYSIDE6_MIGRATION_PLAN.md](./PYQT_TO_PYSIDE6_MIGRATION_PLAN.md) | PyQt6 → PySide6 许可与迁移计划 | 历史计划；PySide6 迁移已完成 |
| [PYSIDE6_TARGET_ARCHITECTURE.md](./PYSIDE6_TARGET_ARCHITECTURE.md) | 单一 Qt binding、UI / Pipeline 边界和迁移 worktree 规则 | 当前运行架构 |
| [UNIFIED_ASR_EVENT_PIPELINE_PLAN.md](./UNIFIED_ASR_EVENT_PIPELINE_PLAN.md) | Apple / Parakeet / MLX 的统一 ASR 事件协议与字幕链迁移计划 | Phase 0–3 完成；Phase 4 待实机验收后评估 |
| [PARAKEET_RELIABILITY_PLAN.md](./PARAKEET_RELIABILITY_PLAN.md) | 连续课堂语音下的 Parakeet 候选段、native-final 对账、低音量预处理与 EOU 实验计划 | Phase 0–2、低音量预处理已实施；等待回放参数实验与实机验收 |
| [NOTCH_LONG_TRANSLATION_DISPLAY_PLAN.md](./NOTCH_LONG_TRANSLATION_DISPLAY_PLAN.md) | 原生刘海中长中文译文的连续 fragment 展示与布局一致性修复 | 已实施；等待 macOS 实机视觉验收 |
| [NOTCH_TRANSPORT_RELIABILITY_PLAN.md](./NOTCH_TRANSPORT_RELIABILITY_PLAN.md) | Python ↔ Swift 刘海快照握手、帧序与故障重放 | 自动验收通过；等待 macOS 实机验证 |
| [DECISIONS.md](./DECISIONS.md) | 需要长期遵守的技术与产品决策 | 持续维护 |
| [CHANGELOG.md](./CHANGELOG.md) | 面向后续开发 Agent 的近期变更摘要 | 持续维护 |

## 现有全局文档

- [Mac App Store MVP 执行计划](../product/MAC_APP_STORE_MVP_EXECUTION_PLAN.md)
- [产品决策记录](../product/PRODUCT_DECISIONS.md)
- [产品与 Mac 发布路线](../PRODUCT_RELEASE_AND_APP_STORE_ROADMAP.md)
- [重构安全网与不变式](../REFACTORING_SAFETY_NET.md)
- [延迟基准](../LATENCY_BASELINE.md)
- [Agent 交接说明](../AGENT_HANDOFF.md)

每次完成一个可验证开发批次，必须按
[维护协议](./MAINTENANCE_PROTOCOL.md) 更新 `CHANGELOG.md`；影响实时
不变式或验收门槛时同时更新 `AGENT_HANDOFF.md`。

## 强制边界

- 不为整理代码而改变 Apple 草稿、ASR、模型路由、字幕节奏或上下文策略。
- 每一批 UI/绑定迁移都必须通过全量测试，并做对应 macOS 实机验证。
- 本机 `config.ini`、Keychain、`transcripts/`、`logs/` 不进入 Git；发布前运行 `python3 tools/release_audit.py .`。
- UI 视觉素材日后必须替换为拥有对外/商业分发权的资源；当前动漫角色素材不属于发布资产。
