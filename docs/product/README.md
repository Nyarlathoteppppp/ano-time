# AnoTime 产品开发管理

这里是面向 **Mac App Store MVP** 的产品与交付单一入口。它不保存 API Key、真实课堂内容、用户日志或供应商后台凭据。

## 文档索引

| 文档 | 用途 | 状态 |
| --- | --- | --- |
| [MAC_APP_STORE_MVP_EXECUTION_PLAN.md](./MAC_APP_STORE_MVP_EXECUTION_PLAN.md) | MVP 范围、原生架构、云服务、订阅、审核和 GitHub 交付流程 | 当前主计划 |
| [PRODUCT_DECISIONS.md](./PRODUCT_DECISIONS.md) | 已确认决策、待确认 Gate 与不做事项 | 持续维护 |

## 工作规则

```text
Issue 写清用户结果与验收
→ 小 PR / 单一变更
→ 自动测试
→ 真机权限与长会话验证
→ TestFlight / 审核 Gate
→ 更新本目录的状态与决策
```

旧版技术路线、PySide6 迁移、ASR 事件协议和运行交接仍保留在
[`docs/development/`](../development/)，它们是现有原型的事实记录；本目录定义的是
**可售、可审核的原生 macOS 产品**如何推进。
