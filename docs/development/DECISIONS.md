# 开发决策记录

本文件记录已经确定、后续代码必须遵守的决策。新决定只追加，不改写历史结论；被取代时标记“已替代”。

| 日期 | 决策 | 原因 / 约束 | 状态 |
| --- | --- | --- | --- |
| 2026-08 | macOS 优先；iPhone/iPad 延期 | 手机端不能复用 Mac 的系统音频、悬浮层与刘海实现，会分散产品验证资源 | 生效 |
| 2026-08 | 不购买 PyQt6 商业许可 | PyQt6 免费版为 GPLv3，不适合目标闭源体验版 | 生效 |
| 2026-08 | 近期迁移 PySide6，长期再评估 SwiftUI/AppKit | PySide6 能保留当前 Python Pipeline；直接重写原生 UI 收益低、风险高 | 生效 |
| 2026-08 | 翻译实时路径优先级：Apple 草稿 > Preview > Final | 首条可读字幕与课堂体验优先；远程模型不能阻塞 Apple 草稿 | 生效 |
| 2026-08 | Smart Hybrid 仅开发者配置；普通用户使用 Single Model / 未来 AnoTime Cloud | 不把供应商、额度与 API 配置暴露给体验用户 | 生效 |
| 2026-08 | 用户 API Key 只放 macOS Keychain | 不写入 Git、README、日志或导出配置 | 生效 |
| 2026-08 | 当前动漫角色素材不可用于外部/商业发布 | 未完成商业授权审计；未来 Beta 和商店素材必须替换 | 生效 |

## 迁移期间绝不顺手修改的内容

- Apple ASR / Apple Translation 调用和延迟路径。
- `Pipeline` 的 Preview / Final 并发、deadline、latest-wins 策略。
- 课程档案、Smart Hint、术语注入和上下文预算。
- Swift notch 的输入协议与动画语义。
- 模型供应商路由、限额、费用统计。

需要变更以上内容时，必须单独建立计划、单独测试、单独提交。
