# 翻译方式：原样翻译与语境推测

状态：2026-08-26 已实施，等待真实课堂音频验收。

## 用户语义

Home 页提供两档翻译方式，保存后下一次 Launch 生效：

- `原样翻译（常规 ASR 纠错）`：保留 AnoTime 原有纠错能力。模型仅在当前句和课程领域足以确定原词时，静默修正明显 ASR 错词；否则按照识别到的英文翻译。
- `语境推测（增强上下文纠错）`：模型可更积极地结合当前句、历史上下文、课程主题、课程档案和术语表推断说话者原意，但不得凭空补充缺少证据的内容。

两档都只返回完整目标语言译文，不显示候选、置信度、解释或“推测（字面翻译）”括号。此前设计的括号不确定性标记在实装前即被产品决定替代，不是当前输出合同。

## 配置和运行边界

- 配置键：`[translation] interpretation_mode`，合法值为 `standard` / `contextual`，缺失或非法时使用 `contextual`。
- Dashboard 将选择写入 `TranslationSettings`；每次 Launch 经不可变 `SessionSettingsSnapshot` 固定本次会话，运行中修改不会改变正在处理的句子。
- `translation_workflows.providers.translator_options` 把模式传给所有远程 `Translator` 实例，包括 Smart Hybrid final/preview/bridge、Single Model 和 Qwen-MT。
- Qwen-MT 没有 system message，因此规则随 `translation_options.domains` 传递。
- Apple Only 使用系统 Translation framework，无法注入提示词；Home 选择器在 Apple Only 时禁用。
- 英文 ASR、finalized correction 表、segment ID、字幕记录、流式展示和录音均不修改。
- 不做输出正则、括号解析或代码级猜词。

## 配额

Smart Hybrid 的 TPM 和 Cloudflare neuron 预留使用两档提示词中较长者估算固定开销。这样切换模式不会低估供应商限制，也不会在运行时改变路由预算。

## 实机验收

使用同一段许可课堂音频分别运行两档：

1. 正常技术句的译文不应因增强模式而凭空增加信息。
2. 明显且确定的 ASR 错词，两档都应能够正常纠正。
3. 只有依赖跨句上下文才能恢复的错词，语境推测应优于原样翻译。
4. 两档都不得输出备选词、解释文字或不确定性括号。
5. preview 与 final 不应因模式指令产生异常反复改写；若增强模式跳动明显，应收紧该模式提示词，不得修改字幕记录模型。

回滚只需移除 Home 选择器、配置字段和双提示词选择；不得回滚 ASR、工作流或字幕展示层。
