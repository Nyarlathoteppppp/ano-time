# AnoTime macOS App Store MVP：执行计划

> 状态：产品与工程规划；**不代表当前 Python/PySide6 原型已可提交 App Store**。
> 目标：以最短路线发布一个可审核、可收费、可稳定迭代的 macOS MVP，而不是重做所有已有实验功能。
> 产品承诺：用户选择音频来源、授权并开始后，尽快看到英文和中文；停止后得到本地双语记录。
> 系统要求：**Requires an Apple silicon Mac with macOS 26.0 or later.**

---

## 1. MVP 合同

### 1.1 谁在用、为什么付费

首发用户是英语授课环境中的留学生与英文会议参与者。付费理由不是“可选 12 个模型”，而是：

```text
选择系统音频或麦克风
→ 看懂正在说的话
→ 不被字幕挡住或闪烁干扰
→ 结束后直接得到可复习的双语记录
```

### 1.2 首发包含

| 能力 | MVP 行为 | 不能牺牲的规则 |
| --- | --- | --- |
| 音频 | System Audio、Microphone、Both；通过 ScreenCaptureKit 与系统权限流程选择内容 | 权限失败必须可解释、可重新授权。 |
| 英文 ASR | 一个 Apple 原生生产后端 | 持续 partial；ASR 不可用时清楚提示，不能假装正在翻译。 |
| 快速中文 | Apple 本地草稿优先显示 | 绝不等待云端 AI、记录写入或 UI 动画。 |
| AI Final | AnoTime Cloud 输出 Preview/Final，修正术语与 ASR 错误 | 失败只能保留已有草稿，不能清空字幕或阻塞下一句。 |
| Smart Hint | 独立后台按 session 生成主题/关键词，作为附加上下文 | 不占用实时请求队列，不保存原文，不影响翻译失败处理。 |
| 课程资料 | 课程主题、术语、保护词、ASR 纠错；资料仅本地提取后由用户确认 | 不把完整 PDF/PPT 放进实时 Prompt。 |
| 展示 | `Compact Overlay`（紧凑字幕）、`Standard Overlay`（可调窗口） | 表示方式不能反向控制 ASR、翻译、记录或 session 生命周期。 |
| 记录 | 自动保存本地 bilingual transcript；能定位、导出与删除 | 只写 final；磁盘写入在后台，不得阻塞字幕。 |
| 商业 | 3 小时受邀体验；订阅解锁 AnoTime Cloud 额度 | 所有权益和计费由服务端/StoreKit 验证，客户端不可信。 |

### 1.3 首发不包含

详见 [`PRODUCT_DECISIONS.md`](./PRODUCT_DECISIONS.md)。最重要的是：不把现有多 Provider、Parakeet/MLX、动漫视觉、云同步或 iOS 拉进首发。

### 1.4 字幕卡默认方案

MVP 默认采用**同一张双语字幕卡**：英文在上、中文在下；两者共同属于同一个 semantic segment。

```text
Gradient descent minimizes the loss.
梯度下降用于最小化损失。
```

原因：一个 segment 只有一套 revision、滚动、长句裁切与最终替换规则。拆成两个独立框会制造不同步、一个框提前消失、滚动锚点不一致等问题。Compact Overlay 只显示当前中文或最新短双语，不承担历史滚动。这个默认将在原生 UI 原型中确认后固化。

---

## 2. 最小可审核架构

### 2.1 原则：Native-first，现有原型是行为参考，不是 App Store Runtime

当前 Python/PySide6 代码是极有价值的原型、基准、测试素材和产品行为参考；但 Mac App Store 版不应依赖项目内 `.venv`、shell、AppleScript、用户机器运行时编译的 Swift helper 或散落的后台进程。

正式分发目标：

```text
AnoTime.app (Xcode / Swift)
├─ App shell: SwiftUI + AppKit
│  ├─ Onboarding / permissions / settings
│  ├─ Compact + Standard overlay
│  ├─ Menu bar / pause / stop
│  └─ Local session history
├─ SubtitleCore (pure Swift package)
│  ├─ ASRHypothesis / segment / revision / stale-result gate
│  ├─ Stable prefix / segmentation / presentation policy
│  └─ Transcript event contract
├─ Native services
│  ├─ ScreenCaptureKit capture
│  ├─ Apple ASR adapter
│  ├─ Apple Translation draft adapter
│  ├─ Keychain / file sandbox / local SQLite
│  └─ StoreKit 2 entitlement client
└─ Cloud transport
   ├─ authenticated HTTPS + SSE streaming
   └─ no vendor API key in the app
```

原型与正式 App 的关系：

| 当前模块 | 正式 App 处理方式 |
| --- | --- |
| `ASRHypothesis → ASRSubtitleCoordinator` | 迁移为 Swift `SubtitleCore` 的第一批领域逻辑；保留同一不变式和 trace 测试。 |
| Apple ASR / Apple Translation | 用公开 Apple Framework 的 Swift adapter 重写；作为唯一商店生产 ASR/草稿。 |
| Preview/Final、课程档案、Smart Hint | 保留产品语义；网络实现替换为 AnoTime Cloud transport。 |
| PySide6 控制中心、Python 玻璃、Swift helper IPC | 只作为 UX/行为参考；不打入商店二进制。 |
| Parakeet/MLX、Provider router benchmark | 留在 `experiments/`；仅用于研发决策。 |

这不是“现在推倒重写”。先移植一个狭窄、可卖的 Apple-only 纵切：Capture → Apple ASR → Apple Draft → Cloud Final → Overlay → Transcript。旧代码继续作为延迟/行为回归基线。

### 2.2 App Sandbox、权限与 Bundle 规则

在第一个 Xcode target 创建时就启用 Sandbox，而不是最后再补。

| 项目 | App / Xcode 配置 | 运行规则 |
| --- | --- | --- |
| Sandbox | `com.apple.security.app-sandbox` | Mac App Store 强制；所有文件、网络、helper 都按沙盒设计。 |
| 网络 | `com.apple.security.network.client` | 只访问 AnoTime Cloud；TLS 校验始终开启。 |
| 麦克风 | `com.apple.security.device.microphone` + `NSMicrophoneUsageDescription` | 用户选 Microphone/Both 时才请求。 |
| 语音 | `NSSpeechRecognitionUsageDescription`，并以实际 Apple ASR API 决定额外能力 | 首次使用 ASR 前解释用途；availability 失败可恢复。 |
| 系统音频 | `NSScreenCaptureUsageDescription` + ScreenCaptureKit | 使用系统 content-sharing/picker；明确展示正在捕获什么，Stop 后立即停止。 |
| 用户资料 | User Selected File read-only entitlement + `NSOpenPanel` | 仅当用户主动添加 PDF/PPT 时读取；安全范围访问结束即释放。 |
| 本地资料 | `Application Support/AnoTime`（sandbox container） | transcript、SQLite、术语档案、缓存都在容器内；不写桌面或任意路径。 |
| Keychain | 默认 Keychain access group | 只保存匿名安装令牌、refresh token、BYOK Key；绝不存服务商共享 Key。 |

**审核边界**：不使用私有 API、不会静默录音、不会捕获/上传原始音频到 AnoTime Cloud；系统音频模式让用户通过系统控件选择内容。所有权限解释必须与实际操作一致。

### 2.3 系统版本 Gate

当前原型声明 Apple `SpeechAnalyzer` / `SpeechTranscriber` 与 Apple Translation 路线需要 macOS 26+。首发已经锁定为 Apple silicon + macOS 26.0+；不做 macOS 14–25 或 Intel fallback。这个范围确保本地 ASR、Apple 草稿与权限流程都是一条可测试的生产路径。

---

## 3. AnoTime Cloud：不泄露 Key，也不让慢请求堵住用户

### 3.1 最小服务，不做微服务

```text
AnoTime macOS App
  ├─ local Apple ASR + Apple draft
  └─ HTTPS/SSE → AnoTime Cloud
                  ├─ anonymous session auth / invite redemption
                  ├─ entitlement + active-minute ledger
                  ├─ realtime translation scheduler
                  ├─ primary provider + one fallback
                  ├─ Smart Hint job
                  └─ StoreKit server verification / notifications

PostgreSQL
  ├─ installations / invite_redemptions
  ├─ entitlements / subscription_transactions
  ├─ live_sessions / usage_minute_buckets
  ├─ usage_events (tokens, cost, latency, error class)
  └─ no transcript text by default
```

第一版是一个版本化 API + 一个关系数据库；不需要 Kubernetes、Kafka、复杂微服务或用户可选模型池。

### 3.2 身份、3 小时体验与付费权益

**受邀 Beta：**

1. 用户兑换一次性邀请码；
2. App 生成随机 installation ID，服务端返回可撤销的 token；二者只存 Keychain；
3. 服务端只在有有效翻译工作的 active-minute bucket 扣减，最多 180 分钟；
4. 每安装仅一个 active session；同时限制 token、RPM、并发和 IP 异常；
5. invite/installation 只用于反滥用，不能制作硬件指纹或收集不必要个人数据。

**商店订阅：**

1. 使用 StoreKit 2 auto-renewable subscription；应用内解锁云端数字功能必须走 IAP；
2. App 将已验证的 transaction JWS 发给服务端；服务端再向 Apple 验证，并记录原始 transaction 的 entitlement；
3. App 每次启动与回前台读取 `Transaction.currentEntitlements`；服务端接收 App Store Server Notifications，处理续费、取消、宽限期和退款；
4. 不要求注册：新设备通过 StoreKit entitlement 恢复服务端权益。跨设备 transcript/history 不在 MVP 承诺内；
5. 离线时，云端 Preview/Final 不可用，但本地字幕/草稿按真实可用性继续；绝不能本地伪造已订阅状态。

### 3.3 实时 API 契约和拥挤控制

客户端只发送 ASR 文本与预算内上下文，不发送音频；服务端选择模型。

```json
POST /v1/live/translate
{
  "session_id": "opaque-id",
  "segment_id": "opaque-id",
  "revision": 7,
  "stage": "preview | final | smart_hint",
  "current": "English ASR text",
  "context": {"topic": "...", "terms": ["..."]}
}
```

返回 SSE：`delta`、`completed`、`error`；每个事件带 `segment_id`、`revision`、`stage`。客户端的既有 stale-result gate 保证旧响应不能覆盖新字幕。

| 层级 | 规则 | 目的 |
| --- | --- | --- |
| App 内 | Apple 草稿独立；Preview latest-wins；Final 不被 Preview 失败冷却；Smart Hint 是低优先级后台任务 | 速度第一。 |
| 单 Session | 同时至多 1 个 Preview 流、1 个 Final；新 Preview 取消/淘汰旧 revision；Final 预留独立 slot | 老师连续讲话时不积压。 |
| 用户 / 安装 | 活跃时长、并发 1、RPM、输入/输出 token、单句长度限制 | 防刷与可预测成本。 |
| 服务端全局 | 有界队列、按活跃 session 公平调度、provider circuit breaker、超时、fallback | 一个供应商慢/限流不拖垮所有用户。 |
| 数据 | 只记录 stage、token、耗时、provider class、错误码和时间 | 可以计费/排障，但默认不保存课堂原文。 |

Provider 不可用时顺序固定：**保留 Apple 草稿 → 返回可恢复状态 → 服务端 fallback → 超时后丢弃旧 revision**。任何失败都不能阻塞 ASR 或让字幕空白。

### 3.4 Smart Hint

Smart Hint 每约 4 分钟读取本地已 finalized 英文的受限摘要窗口；它只调用 `/v1/hints`，返回主题与关键词的简短结构化结果。它与手填课程主题共同注入：手填主题优先，Smart Hint 补充。

硬规则：

- 不与 Preview/Final 共用实时并发 slot；
- 超时/失败静默降级，不改变模型路由；
- 不保留原始输入文本，只保留可选的最终 hint 和产生时间；
- 只能影响后续 request 的上下文，不能改写已经显示/记录的字幕。

---

## 4. 订阅、成本和定价 Gate

### 4.1 现在先不定价，但现在就做成本边界

`A$15/月` 是待验证假设，不是商品价格。价格、每月包含时长、超额策略在真实 Beta 数据前不能定。

要收集的最小数据：

| 指标 | 用途 |
| --- | --- |
| 每活跃翻译小时的 input/output token、provider 成本 | 计算毛利下限。 |
| Preview / Final / Smart Hint 的请求数、p50/p95 延迟、失败率 | 选择模型及并发规则。 |
| 每位体验者总活跃分钟、连续会话长度 | 设计月度额度而非拍脑袋。 |
| 权限成功率、首条字幕时间、Stop 后记录打开率 | 判断用户愿不愿意留下。 |

MVP 需要两个可见状态：`remaining trial minutes` / `subscription status`。开发诊断可显示 token 与成本，普通用户不显示 Provider 名与内部费用。

### 4.2 订阅商品原则

- 至少 7 天周期的 auto-renewable subscription；商品名称与权益清楚说明。
- 首发仅一个月度档；不要一开始做月/年/学生/团队/点数包五种 SKU。
- 订阅描述写清：云端 AI Final、Smart Hint、每月包含的活跃翻译额度、耗尽后会发生什么、如何取消。
- Restore Purchases 和断网/退款/宽限期状态是 MVP 的验收项。
- 若后续出售额外云端分钟，单独按 IAP consumable 设计；不与首发订阅混做。

---

## 5. 只用四个 Milestone 推进 MVP

没有“第 17 阶段”。每个 Milestone 完成后都可停下来让真实用户测试，再决定是否继续投入。

### M0 — 产品基线与审核合同

**目标：** 让工程从第一天就不会走到不可审核的死路。

- 锁定最低系统版本、Bundle ID、产品名称、无动漫的视觉方向。
- 建立 Xcode workspace、一个空沙盒 target、CI 构建与最小隐私/权限文案。
- 完成数据流、第三方子处理方、版权/许可证/素材清单。
- 把当前 Python 原型的 Apple 体验录为可重复的行为/延迟 reference。

**完成定义：** 一个签名的空 App 能在目标 macOS 请求并解释对应权限；所有未决产品 Gate 已有 owner 和截止 Milestone。

### M1 — Native Local Vertical Slice

**目标：** 不含订阅也能在真机完整完成一场本地字幕会话。

- ScreenCaptureKit 系统音频/麦克风选择与状态机。
- Apple ASR → Swift SubtitleCore → Apple Translation draft。
- Compact / Standard 双语 overlay；暂停、停止、权限恢复。
- 容器内 SQLite/session transcript：只写 final，后台落盘。

**完成定义：** 连续 60 分钟实机播放/课程：无崩溃、无后台残留、Stop 后记录可读、权限被拒绝时可自救；不依赖 Python、Shell、运行时 Swift 编译或供应商 Key。

### M2 — AnoTime Cloud 与 3 小时受邀体验

**目标：** 10–20 位受邀者能体验 AI Final 而拿不到任一供应商 Key。

- 邀请码、匿名 Keychain token、服务端 180 分钟账本。
- Cloud Preview / Final、一个 primary + 一个 fallback、SSE、限流与可观测性。
- Smart Hint 独立 worker / 低优先级队列。
- 服务端 secret manager、数据保留/删除端点、操作告警。

**完成定义：** 受邀用户从安装到首条字幕不超过五分钟；服务端可撤销 token、限制成本；网络/Provider 失败不会卡住本地草稿。

### M3 — StoreKit、TestFlight 与审核提交

**目标：** 形成可购买、可恢复、可审核的单 App Bundle。

- StoreKit 2 订阅、restore、服务端 entitlement 验证、App Store Server Notifications。
- Privacy Policy、Terms、Support URL、App Privacy 信息、审核演示账号/流程、App Review Notes。
- TestFlight 内测 → 外测；崩溃、权限、网络、成本与退订状态复核。
- 截图/预览只展示真实、无未授权素材的功能。

**完成定义：** 审核人员能无需终端完成授权、开始、停止、查看记录、体验/购买/恢复订阅；所有 URL 可用，服务端在审核期保持在线。

---

## 6. GitHub Projects、Issues、Milestones、PR 与轻量 Kanban

私有仓库 `Nyarlathoteppppp/AnoTime` 是产品代码与规划的唯一 source of truth。现有 `codex/pyside6-migration` 分支只作为原型事实基线；商店工程不能直接把它的运行环境当成产物。

### 6.1 一个 Project 足够

建立 GitHub Project：`AnoTime macOS MVP`。

字段：

| 字段 | 值 |
| --- | --- |
| Status | Backlog / Ready / In progress / Review / Device verification / Beta / Done / Blocked |
| Milestone | M0 / M1 / M2 / M3 |
| Area | Native core / Capture / Subtitle / Cloud / Billing / Privacy / Release |
| Priority | P0 / P1 / P2 |
| Risk | Low / Medium / High |
| Evidence | Test command、真机结论、TestFlight build 或审核链接 |

WIP：`In progress` 总数最多 2；其中 Native Capture/Subtitle 与 Cloud/Billing 不能同时进行大重构。每张卡必须有用户结果、验收条件、失败降级规则和隐私影响。

### 6.2 Labels 与 Issue 模板

建议 labels：

```text
type: feature / bug / spike / security / compliance / release
area: native-core / capture / subtitles / cloud / billing / privacy / ui
priority: p0 / p1 / p2
risk: low / medium / high
needs: device-test / review-note / migration
```

Issue 的最小格式：

```text
User outcome
Scope / out of scope
Acceptance tests (automated + real Mac)
Failure and privacy behaviour
Dependencies / decision links
```

`spike` 只能回答一个有时限的问题，例如“macOS 26+ Speech API 是否可在 Sandbox App 中完成持续系统音频 ASR”；结论必须写回决策文档，不能无限挂着。

### 6.3 PR 规则

- 一张 Issue 对应一个窄 PR；不把 UI 重画、Provider 更换和字幕状态机放进同一 PR。
- PR 描述必须包含：行为变化、测试、真机结果、性能影响、权限/隐私影响、回滚方式。
- 原生 UI PR 附截图/录屏；Capture/permission PR 附目标 macOS 与完整授权路径。
- Cloud PR 附 API contract、限流规则、成本上限、日志是否含文本。
- 合并前：CI、`release_audit`、Code Signing / entitlement 检查（M0 后）、必要的设备测试都通过。

### 6.4 Branch 与发布规则

```text
main                 可由 TestFlight 候选构建
feat/<issue>-...     单一功能
fix/<issue>-...      单一缺陷
release/<version>    仅用于候选修复与元数据
```

生产密钥、`.env`、provisioning profile、私有 transcript、崩溃原始附件永不进入 Git。CI 使用 GitHub Environments 的受保护 secrets；本地开发用独立 `.env` / Keychain。

---

## 7. 测试、性能、隐私与审核 Gate

### 7.1 每个 PR 的最低测试

| Area | 自动测试 | 真机验证 |
| --- | --- | --- |
| SubtitleCore | event trace、stale revision、pause/resume、长句 | 语速变化时字幕不回退、不黏连。 |
| Capture / ASR | mocked sample buffers、权限状态机 | System Audio、Mic、Both、拒绝后恢复、Stop。 |
| Overlay | layout snapshot、long text、compact/standard state | 全屏浏览器/PPT、外接屏、Mission Control、鼠标。 |
| Cloud | contract、auth、quota、SSE cancellation、fallback | 高并发/网络切换、服务端 provider 故障。 |
| StoreKit | StoreKit configuration、restore、entitlement state machine | Sandbox account、退款/取消/宽限期模拟。 |
| Storage | SQLite migration、delete/export、background writer | 60 分钟会话后记录完整且 UI 不掉帧。 |

### 7.2 性能不变式

1. 首条英文、Apple 草稿、AI Preview、AI Final 分开计时；不能用平均总延迟掩盖首条变慢。
2. Apple 草稿不等待 Cloud、Smart Hint、SQLite、动画或账本请求。
3. 所有网络任务有 timeout、cancellation 和 revision gate；停止后旧结果不能重新显示。
4. 用量上报异步、批量、可重试；断网时不影响实时字幕。
5. 超过预算时优雅降级：英文/Apple 草稿继续，明确说明 AI Final 暂不可用。

### 7.3 隐私与安全发布 Gate

- Privacy Policy、服务条款、删除流程、第三方 AI 子处理方与数据保留期限已公开。
- 服务端没有音频持久化；文本日志默认不保留全文；诊断捕获必须显式授权并自动过期。
- 供应商 Key 仅位于服务端 secret manager；客户端没有共享 Key。
- TLS 校验、token rotation、服务器 rate limit、每日预算告警、异常 session kill switch 已启用。
- 用户可在 App 内删除本地记录；账户未注册也能撤销安装 token / 清除本地数据。

### 7.4 提交审核 Gate

- Sandbox、签名、entitlements、Info.plist usage descriptions、Privacy Manifest 与 release bundle 一致。
- App 不包含运行时编译、外部 `.venv`、shell 依赖、未签名 helper 或未授权视觉素材。
- 审核说明给出完整权限步骤、体验方式、测试邀请码/审核入口、网络故障降级说明。
- 订阅商品在 App 内可见、可购买、可恢复，价格与权益描述一致。
- 所有支持/隐私/条款 URL 可访问；App Store 截图和文案不夸大“本地”“无服务器”或系统能力。

---

## 8. 首批 Backlog（按顺序，不并行膨胀）

| 顺序 | Issue | Milestone | 风险 | 完成条件 |
| ---: | --- | --- | --- | --- |
| 1 | 验证 macOS 26 Apple ASR / Translation 的 Sandbox 生产能力 | M0 | High | 在 Apple silicon + macOS 26 真机 capability spike 通过；记录可恢复失败状态。 |
| 2 | 建立 `AnoTimeMac` Xcode sandbox shell、CI 和 bundle identity | M0 | Medium | 签名 App 可启动；无 Python runtime。 |
| 3 | 原生权限状态机与 ScreenCaptureKit source picker | M1 | High | 授权/拒绝/恢复/停止全链真机通过。 |
| 4 | Swift `SubtitleCore` event trace | M1 | Medium | 覆盖 partial→draft→final、stale、pause/resume。 |
| 5 | Apple ASR + Apple draft vertical slice | M1 | High | 60 分钟本地会话稳定；英文/中文/record 可用。 |
| 6 | Compact / Standard overlay 无动漫 UI | M1 | Medium | 长句、全屏、外接屏与窗口切换验收。 |
| 7 | 本地 SQLite transcript 与删除/导出 | M1 | Low | 只写 final；不阻塞字幕。 |
| 8 | Cloud auth/invite/3h usage ledger | M2 | Medium | Key 不出服务端；成本和撤销可观测。 |
| 9 | SSE Preview/Final、排队与 fallback | M2 | High | Provider 故障不影响 Apple 草稿。 |
| 10 | Smart Hint 独立后台任务 | M2 | Medium | 不挤占实时并发且不留全文日志。 |
| 11 | StoreKit 2 + server entitlement | M3 | High | 购买、恢复、取消、过期与离线状态正确。 |
| 12 | TestFlight / 审核材料 / release audit | M3 | Medium | 外部测试与审核 Gate 全通过。 |

---

## 9. 参考规则

- Mac App Store 分发必须启用 App Sandbox；网络、麦克风和用户选取文件均需匹配 entitlement，权限仍需用户显式同意。
- ScreenCaptureKit 是系统音频/屏幕内容捕获的公开 API；必须展示清楚的用户选择和录制用途说明。
- StoreKit auto-renewable subscription 需要持续价值，周期至少七天；云端 entitlement 应由服务端验证并接收状态更新。
- 审核版本必须完整、可使用、可解释；有服务端或登录时必须提供审核能走通的方式。

官方资料：

- [App Sandbox](https://developer.apple.com/documentation/security/app-sandbox)
- [ScreenCaptureKit](https://developer.apple.com/documentation/screencapturekit)
- [Speech authorization](https://developer.apple.com/documentation/speech/asking-permission-to-use-speech-recognition)
- [StoreKit server entitlement](https://developer.apple.com/documentation/StoreKit/determining-service-entitlement-on-the-server)
- [App Review Guidelines](https://developer.apple.com/app-store/review/guidelines/)
