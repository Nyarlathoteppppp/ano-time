# AnoTime：体验版、云服务与双平台 App Store 路线

> 状态：设计文档，不改变当前运行代码。
> 范围：macOS 体验版、未来 Mac App Store、未来 iPhone/iPad App Store。
> 产品原则：先让用户在十分钟内听懂一段课或会议；任何商业化、记录和 AI 功能都不能拖慢本地 Apple 草稿路径。

---

## 1. 先给结论

当前 AnoTime 已经接近 **技术用户可长期使用的 macOS 工具**，但还不是可以直接卖给普通用户的 App Store 产品。

最现实的路线不是“先上架，再解决问题”，而是：

```text
当前开发版
  → 受邀 macOS 体验版（2 小时云端试用）
  → 可安装的 macOS Beta
  → AnoTime Cloud + 本地课堂记录
  → Mac App Store
  → 独立的 iPhone/iPad 客户端
```

手机端不是把当前 Mac 程序打包一下就能得到。iPhone/iPad 的系统音频、悬浮字幕和动态岛都受系统约束，必须是独立 SwiftUI 客户端；两端共享的是账号、课程档案、记录和 AnoTime Cloud API。

### 1.1 当前最值得做的体验版

给外部用户体验时，提供：

- macOS only；优先 Apple Silicon + 支持的 macOS 版本。
- System Audio / Microphone / Both 三种音频入口。
- 英文识别、Apple 草稿、云端最终精修、玻璃字幕。
- 课程 / 会议 / 通用三种场景。
- 本地保存双语记录。
- 每个受邀用户有 **2 小时有效翻译额度**。

体验版不要让用户看到 Groq、Cerebras、Gemini、Qwen、Base URL、temperature、VAD 参数或 API Key。它们仅保留给开发者模式和 BYOK 高级模式。

---

## 2. 体验用户的 2 小时如何实现，以及为什么不能直接给 API Key

### 2.1 不能做的事

绝不能把开发者购买的 Groq、Cerebras、Gemini、Qwen 或 DeepSeek Key 写进：

- `config.ini`
- macOS Keychain
- Python 源码、`.pyc` 或打包后的 `.app`
- 桌面启动器、shell 脚本、Swift helper

Keychain 只能防止密钥以明文留在用户磁盘；它不能防止应用运行时把共享密钥取出后被有能力的用户截获。任何放进客户端的共享供应商 Key 都默认会泄露，并可能被刷爆额度。

### 2.2 正确的 2 小时试用模型

```text
AnoTime Beta（用户电脑）
  └─ Keychain：只保存 AnoTime 登录令牌
           │ HTTPS / SSE
           ▼
AnoTime Cloud Gateway
  ├─ 账号、试用、限流、用量账本
  ├─ 服务端密钥（Secret Manager / 环境变量）
  └─ Provider Router
       ├─ 快速 Preview：Cerebras / Groq
       ├─ Final：Gemini / Qwen / 其他
       └─ Fallback：按健康、费用和延迟切换
```

客户端只认识 AnoTime Cloud，不认识供应商密钥。BYOK 是并列的高级模式：用户自己的 Key 仍放其本机 Keychain，并直连用户选定的供应商。

### 2.3 试用额度的服务器规则

“2 小时”不能只靠客户端计时；客户端可被修改。服务端需要同时做三层约束：

| 约束 | 目的 | 推荐规则 |
| --- | --- | --- |
| 试用资格 | 防止一个邀请码无限注册 | 一次性邀请兑换；账户和设备绑定可撤销 |
| 活跃时长 | 让用户有连续听课体验 | 每个存在有效字幕请求的分钟桶扣 1 分钟，最高 120 分钟 |
| 请求 / Token 预算 | 防刷、保护成本 | 按用户、设备、IP 做 RPM、并发、输入/输出 Token 上限 |
| 单会话 | 防止一个体验资格并行转售 | 同时只允许一个 live session |

服务端账本以 **成功接受的翻译请求** 为准。空音频、无字幕和纯客户端空闲不应扣时；同时必须设总 Token 上限，避免攻击者用超长文本烧掉成本。

体验用户首次打开流程应是：

```text
安装 → 登录/兑换邀请码 → 选择音频 → 授权 → Start
```

而不是填五个供应商 API Key。

### 2.4 最小 Gateway，不要一开始做微服务

第一版可以是单个服务：

```text
FastAPI 或 Cloudflare Worker
├─ Auth / Trial
├─ POST /v1/realtime/translate       (SSE)
├─ POST /v1/sessions/{id}/finalize   (总结任务)
├─ GET  /v1/me/entitlement
└─ POST /v1/trials/redeem

PostgreSQL
├─ users
├─ devices
├─ entitlements
├─ sessions
├─ usage_events
└─ trial_redemptions
```

实时输出优先用 **SSE**，因为是服务器向客户端单向连续吐 token；无需先引入 WebSocket。

`/v1/realtime/translate` 的产品契约应围绕任务，而不是供应商：

```json
{
  "session_id": "...",
  "stage": "preview | final | summary",
  "current": "Gradient descent minimizes the loss.",
  "source_language": "en",
  "target_language": "zh-Hans",
  "mode": "lecture",
  "context": {
    "course_profile_id": "machine-learning",
    "topic": "Regularisation and bias-variance trade-off",
    "terms": ["gradient descent", "loss function"]
  }
}
```

服务端才决定具体 Provider、模型、fallback 和成本。开发诊断可以返回 `provider`、`latency_ms`；普通 UI 不应展示这些内部实现。

### 2.5 隐私底线

语音转写和课堂/会议文本本身就是敏感数据。体验版必须在首次云端翻译前明确说明：

- Apple ASR / Apple 草稿在本机完成的部分不上传。
- 远程 Preview / Final 的文本会发送到 AnoTime Cloud 和其选定 AI 供应商。
- 默认不把原始音频上传云端。
- 原始双语记录默认仅保存在本机；云同步必须另行选择开启。
- 用户可删除本地记录、撤销账户、请求删除云端账号和用量数据。

服务端用量日志默认只保留计费所需的：用户、模型、阶段、Token、费用、延迟、时间。不要默认保存完整课堂原文；排障捕获必须显式 opt-in 且有过期时间。

---

## 3. 产品功能分层

### 第一层：第一次使用十分钟内必须体验到

```text
系统音频 / 麦克风
→ Apple 本地实时英文
→ Apple 快速中文草稿
→ 云端 Preview / Final 精修
→ 不挡屏、稳定、可暂停的字幕
```

必须提供一个简洁首页：

```text
Source:     System Audio / Microphone / Both
Translate:  English → Simplified Chinese
Mode:       General / Meeting / Lecture
Profile:    Optional

                         [ Start ]
```

当前控制中心的 Provider、Base URL、stream、ASR 后端、VAD 和定价放到 **Advanced / BYOK**。普通用户只需要看到权限、当前状态、剩余额度和 Start/Stop。

### 第二层：让用户为 AnoTime 付费

- 课程 / 会议 / 通用场景。
- 课程档案：术语、ASR 纠错、禁止翻译词、课程主题。
- 拖入 PDF/PPT 后提取标题和术语候选，用户确认后写入课程档案。
- 停止后生成可编辑的双语 Transcript。
- Meeting Summary：摘要、决定、待办、负责人。
- Lecture Notes：主题、关键概念、术语、可能遗漏点、复习提纲。

### 第三层：形成留存，而不是第一版就做

- Session 历史页。
- 按课程 / 会议 / 日期搜索。
- 跨 Session 问答，例如“这三周关于 entropy 讲了什么”。
- 可选端到端加密同步与跨设备访问。

不要让第三层阻塞体验版。先保证一场课程结束后的记录和总结真正有用。

---

## 4. 课程档案与记录的正式数据模型

当前已有 Course Profile、术语、ASR 纠错、Smart Hint 和本地 transcript。下一步不要继续堆 Prompt，而是固定为显式领域对象。

```text
CourseProfile
├─ id / display_name                     # 例如 Machine Learning，不用学校代码
├─ mode                                  # lecture / meeting / general
├─ domain_description
├─ glossary_entries
├─ asr_corrections
├─ protected_terms
├─ source_documents                      # 用户选定的 PDF/PPT；本地优先
└─ model/display preferences (optional)

Session
├─ id / started_at / ended_at / duration
├─ profile_id / topic / mode
├─ local_transcript_path
├─ summary_status
├─ local_summary_path
└─ cloud_sync_state

TranscriptSegment
├─ session_id / ordinal / timestamp
├─ final_source
├─ final_translation
└─ provider metadata (diagnostic only)
```

PDF/PPT 的正确流程：

```text
用户选文件
→ 本地文本提取
→ 提取标题、术语、定义候选
→ 用户勾选/编辑
→ 保存到 CourseProfile
→ 实时翻译仅注入预算内的相关术语
```

不要把整份 PDF/PPT 连同每一个实时请求发送给模型。这样会同时增加成本、延迟、隐私风险和幻觉概率。

---

## 5. 现有工程与目标工程的关系

现有项目已经具备可复用的边界：

| 现有部分 | 商业版中的角色 | 处理原则 |
| --- | --- | --- |
| Apple ASR / Apple draft | 本地极速路径 | 保持本地，绝不经过 Cloud |
| `TranslationWorkflow` | 客户端翻译工作流 | 增加 Cloud workflow，不重写现有 BYOK |
| `HybridTranslator` | BYOK 开发者路由 | 保留为开发/高级模式，不暴露给普通用户 |
| `Translator` | OpenAI-compatible transport | 可以成为 Cloud 服务端 provider adapter 的参考 |
| ContextPolicy / CourseProfile | 上下文与术语层 | 保持本地快照、预算和现有优先级 |
| Transcript recorder | 本地 Session 输出 | 升级为 Session Index，不阻塞字幕 |
| Swift notch / Qt glass | macOS 渲染层 | 与云端协议隔离 |

建议目标边界：

```text
Client
├─ Capture / ASR / Apple Draft
├─ Subtitle presentation
├─ Session local store
├─ Course profile
└─ TranslationTransport
   ├─ BYOK transport
   └─ AnoTime Cloud transport

Cloud
├─ Auth and entitlement
├─ Realtime translation route
├─ Provider adapters and routing
├─ Usage ledger
└─ Summary job
```

不要现在把所有 Python 调用改成 `async`，也不要为了“接口漂亮”替换已经稳定的 Preview / Final / latest-wins 链路。Cloud transport 应作为一个新增实现接入当前工作流契约。

---

## 6. PyQt6、开源许可与 App Store

### 6.1 当前事实

当前工程依赖 `PyQt6`，其免费分发版本是 **GPLv3**，不是 LGPL。项目当前根许可证是 MIT，且代码历史包含上游 `Vanyoo/realtime-subtitle` 的贡献，原作者版权和 MIT 通知必须保留。

因此，不能把“继续使用免费 PyQt6 + 闭源收费 App Store”当作无风险路线。许可选择必须在首次向外分发专有 Beta 前定下来。

### 6.2 可选路线

| 方案 | 代码量 | 适合什么阶段 | 判断 |
| --- | ---: | --- | --- |
| 保持 PyQt6 GPLv3，整个客户端开源 GPLv3 | 极低 | 开源体验版 | 不适合闭源商业产品；也要单独评估 App Store 条款兼容性。 |
| 购买 PyQt6 商业许可 | 低 | 快速发布专有 macOS Beta | 不用大改代码；有许可证成本。 |
| PyQt6 迁移 PySide6 | 中 | 想脱离 Riverbank 商业绑定 | 生产文件约 14 个直接导入 PyQt6，机械迁移不难，但要完整回归窗口、信号、打包和许可合规。 |
| macOS 改 SwiftUI/AppKit | 很高 | 正式 Mac App Store 产品 | 最符合原生权限、打包和体验，但需重写控制中心/玻璃 UI。 |

推荐决策：

1. 外部体验测试前，先确定开源 GPL 还是购买/迁移许可；不要忽略这个问题。
2. 真正 App Store 的长期路线优先 SwiftUI/AppKit；不要指望当前 Python + AppleScript 启动器直接过审核。
3. 涉及 GPL/LGPL/App Store 分发时，发布前请做专业许可证合规确认；本文件不替代法律意见。

### 6.3 当前 macOS 打包和 App Store 的具体差距

当前安装方式会创建桌面 AppleScript `.app`、项目内 `.venv`、在用户机器编译 Swift helper，并通过 shell / `nohup` 启动后台 Python。它很适合开发，但不符合正式 App Store Bundle 的要求。

正式 Mac target 必须完成：

- 一个 Xcode 构建、签名的 `.app`，固定 Bundle ID。
- 所有 Swift helper 预编译并作为 Bundle 内资源 / XPC helper；不能首次启动时在用户机器编译。
- 不再创建桌面启动器、外部 `.venv`、LaunchAgent 或用户退出后仍继续运行的后台服务。
- 正式 entitlements、沙盒目录、权限用途描述、隐私清单。
- ScreenCaptureKit 使用系统内容选择器和明确权限流程。
- Developer ID 签名与 notarization 用于官网 DMG；App Store 使用 App Store 分发签名与 Transporter/Xcode 上传。
- 真实 Mac 的崩溃、权限、全屏、外接显示器测试。

---

## 7. iPhone/iPad：必须是独立产品，不是 Mac 的缩小版

### 可以共享

- AnoTime Cloud 账号、试用、订阅和额度。
- Course Profile、术语、Session、云端 Summary。
- SwiftUI 设计系统和 API 契约。
- BYOK 仅作为高级选项，且需 Keychain 存储。

### 不能假设共享

- iPhone 不允许一个普通应用像 macOS 一样任意绘制常驻在其他应用上方的字幕玻璃窗。
- iPhone Dynamic Island 是 Live Activity，不是自由浮窗；有尺寸和更新数据限制，不能承载完整滚动双语 transcript。
- iOS 系统音频捕获必须使用公开系统 API 和系统选择器，能力受系统版本、用户授权和使用场景限制。它不能成为“任何 App 都像 Mac 一样无感监听”的承诺。

推荐 iPhone 1.0：

```text
Mic / 录音文件 / 支持的内容共享捕获
→ 全屏字幕界面
→ Live Activity 只显示简短当前状态或最新短译文
→ 云端同步后的 Session / Summary / Ask
```

因此优先级是：先完成 Mac 产品和 Cloud API 契约，再开始 iPhone SwiftUI。否则会同时维护两个不同音频捕获和 UI 平台，进度会失控。

---

## 8. 发布前必须补齐的非功能性要求

### 8.1 体验版 Release Gate

- 新 Mac 用户从下载到首条字幕不超过 5 分钟；权限失败必须有明确修复路径。
- 连续 60–120 分钟系统音频测试：无崩溃、无多个 helper 残留、Stop 后资源释放。
- 网络失败、供应商限流、Apple Translation 不可用时仍保留英文/Apple 草稿，不出现空白或卡死。
- 不同显示器、全屏浏览器、Zoom、PPT、物理刘海/玻璃模式测试。
- 不把开发日志、私人课程档案、个人 API Key、`config.ini`、运行记录打进安装包。
- 用户可一键导出、定位和删除本地记录。

### 8.2 安全和隐私 Release Gate

- 供应商主密钥仅存在服务端 secret store。
- Client access token 使用 Keychain；短期 access token + 可撤销 refresh token。
- API 限流、设备/会话并发限制、异常 Token/请求告警。
- 传输 TLS 验证必须开启；不得为方便网络绕过证书校验。
- 隐私政策、服务条款、数据保留/删除说明、第三方 AI 披露。
- 所有 UI 使用的图片、图标、字体、音效和示例 transcript 必须确认拥有商业分发权。当前带有第三方动漫风格素材的视觉资源不能默认用于商业 App Store 发布。

### 8.3 商店审核 Release Gate

- 可用的审核账号或完整 Demo Mode；服务端审核期间在线。
- App 内权限说明清晰、与真实行为一致。
- 若销售云端翻译、订阅或数字功能，使用 StoreKit / App Store In-App Purchase，并让后端验证购买 entitlement。
- 帐号注册时提供账号删除路径；需要第三方登录时评估 Sign in with Apple 要求。
- App Store 截图展示真实功能，而不是只有角色图或标题页。

---

## 9. 分阶段工程计划

### P0：产品和合规决策（先做）

**目标**：确认后续分发不被许可或素材问题卡死。

- 确定 PyQt 商业许可 / PySide6 / GPL 开源体验版三选一。
- 做代码、依赖、素材、字体、上游版权清单。
- 写隐私政策草案、记录保留与删除策略。
- 确定体验用户画像：英语技术课程留学生优先，先不承诺所有会议软件和所有手机音频。

**验收**：能明确回答“谁的 Key、谁的数据、谁拥有代码、体验版可发给谁”。

### P1：受邀 macOS 体验版（2 小时）

**目标**：10–20 位外部用户能安全开始，无需填供应商 Key。

- AnoTime Cloud 最小 Gateway、邀请码、2 小时 entitlement、用量账本。
- 客户端增加 Cloud 作为普通用户默认引擎，BYOK 放 Advanced。
- 极简 onboarding、权限预检、错误恢复页面。
- 外部 DMG：Developer ID 签名和 notarization；不要先承诺 App Store。

**验收**：服务端看得到每位体验者剩余额度和异常成本；任何测试用户都拿不到供应商 Key；一次真实课堂成功完成 Start → 字幕 → Stop → 本地记录。

### P2：Session 与可见的课后价值

**目标**：用户不是只“看过字幕”，而是留下可复习内容。

- SQLite Session Index。
- Transcript 浏览、搜索、导出、删除。
- Stop 后异步 Summary；失败不影响 transcript。
- Meeting / Lecture 两种模板。

**验收**：一小时课程结束后，用户可在 30 秒内打开双语记录和可读总结。

### P3：课程档案和资料上下文

**目标**：让技术课翻译明显优于通用翻译。

- Course Profile 管理页。
- PDF/PPT 本地提取和术语候选确认。
- 术语优先级和 Prompt 预算；不发送整份材料到实时请求。
- 历史课程回归集，用于 ASR 纠错和术语保护测试。

**验收**：Machine Learning / AI Planning 等不同档案可正确切换，不泄漏词表或上次课程上下文。

### P4：Mac App Store 工程化

**目标**：形成可审核的单 App Bundle。

- 处理 PyQt/SwiftUI 最终技术决策。
- 移除开发期桌面启动器、运行时编译和散落 helper。
- Xcode target、entitlements、签名、sandbox、崩溃报告和隐私清单。
- TestFlight Mac 内测，再提交 Mac App Store。

**验收**：无需终端、无需 Homebrew、无需用户手动运行安装脚本；TestFlight 外部测试稳定。

### P5：iPhone/iPad 客户端

**目标**：提供移动场景和历史记录，不承诺复制 macOS 全部能力。

- 原生 SwiftUI App + Account / Session / Course Profile。
- 麦克风、录音文件、系统允许的内容共享捕获。
- Live Activity 仅显示简短状态；完整字幕在 App 内。
- 与 Mac 共用 AnoTime Cloud、购买 entitlement 和同步记录。

**验收**：手机端能看历史记录、开始一次支持的实时转写、完成订阅验证；不依赖 Mac 专属 helper。

---

## 10. 当前不应优先做的事

- 再增加多个公开模型供应商。
- 把全部实时 Pipeline 改成 async。
- Kubernetes、微服务、复杂队列系统。
- 跨课程 Ask 功能先于稳定的 Session / Summary。
- 在没有 Cloud Gateway 前把共享 API Key 发给体验者。
- 直接为 iPhone 复制现有刘海/玻璃窗口；平台能力不同。

---

## 11. 官方资料

- [Riverbank：PyQt 许可](https://riverbankcomputing.com/software/pyqt)
- [Riverbank：PyQt 商业许可 FAQ](https://riverbankcomputing.com/commercial/license-faq)
- [Qt for Python / PySide6 许可](https://doc.qt.io/qtforpython-6/)
- [Apple App Review Guidelines](https://developer.apple.com/app-store/review/guidelines/)
- [Apple TestFlight](https://developer.apple.com/testflight/)
- [Apple ScreenCaptureKit](https://developer.apple.com/documentation/ScreenCaptureKit)
- [Apple ActivityKit / Live Activities](https://developer.apple.com/documentation/ActivityKit)
- [Apple In-App Purchase](https://developer.apple.com/in-app-purchase/)
