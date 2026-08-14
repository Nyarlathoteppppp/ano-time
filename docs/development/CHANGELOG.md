# 面向后续开发的近期变更

这里只记录对后续开发判断有帮助的事实，不复制完整 Git 日志。

## 2026-08-14

- `glass subtitle resize`：玻璃字幕保持单一、按时间顺序的滚动投影；未保留试验性的“当前句固定舞台/历史区隔离”布局，避免新增字幕时整块历史区重新排版。恢复 70% 不透明的圆角玻璃背景和原字号，并新增右下角可见 `◢` 拖拽把手；原有 8px 边缘/角落缩放仍保留。把手在初始化及 `showEvent` 都显式定位，规避隐藏 QWidget 首次显示前不发 `resizeEvent` 而落在 `(0,0)` 的 Qt 行为；尺寸继续保存至 `glass/geometry`，受最小 320×140 约束。未使用 `QSizeGrip` 或自定义 cursor（macOS 26 / Qt 6.11 切换模式时存在崩溃路径）。验证：玻璃/刘海 targeted 47 项、全量 486 项、release audit 与 `git diff --check` 通过；仍需实机拖动右下角并重启确认尺寸恢复。

- `native notch transport reliability`：修复“玻璃字幕持续更新而物理刘海停在旧帧/不显示”的 Python ↔ Swift helper 传输边界。helper 先发 `ready`，Python 再重放完整有界快照；每帧携带 helper generation 与单调 `frameId`，Swift 丢弃旧帧并在主线程提交状态后发 `applied`。状态帧也携带完整快照，避免 latest-only queue 以空 status 覆盖字幕；helper stdout/pipe 失败会按退避重启并在下一次 ready 重放。原生侧只在真实内容/暂停/活动状态变化时触发展开或收起，重复状态不重启动画或布局收缩。未改 ASR、翻译、glass semantic record 或 fragment 策略。验证：刘海 targeted 53 项、全量 485 项、release helper build、Swift planner、release audit 与 `git diff --check` 通过。遗留：必须在真实 Mac 连续系统音频下验收刘海 → 玻璃 → 刘海、暂停/恢复与长中文，并核对 `notch_transport` ack。

- `Parakeet low-volume input`：新增默认关闭、仅 Parakeet EOU 可见的“低音量增强”控制中心选项，保存为 `transcription.parakeet_adaptive_gain`。开启时只在 Python → Parakeet helper PCM 边界对 RMS 0.0015–0.020 的非静音弱音提高到目标 0.035（最多 4 倍）；静音、正常音量、Apple/MLX、capture、VAD、Apple Translation 和 Smart Hybrid 均不变。Diagnostics 每两秒记录 pre-gain RMS / gain，不记录音频内容。验证：数学边界、PCM 写入、面板可见性、配置 round-trip 与全量 485 项通过。遗留：用同一许可回放分别比较 Apple 与开启/关闭 Parakeet 的漏识别、首 partial、错误识别与资源；不得由该选项引入并行 Apple fallback。

- `GitHub maintenance`：新增 macOS CI（Python 全量回归、release Swift helper、planner、release audit）、隐私安全 Bug 表单和 PR 验收模板；`GITHUB_WORKFLOW.md` 规定 Project、标签、分支保护与实机验证闭环。当前 GitHub 远端尚无 Actions、Issue、PR 或分支保护；本批未 push、未创建远端 Issue/PR、未修改远端设置。验证：workflow 文件、模板和文档已纳入 release audit；遗留：仓库管理员需按文档创建 Project/标签并保护 `master`。

- `notch long translation display`：实施原生刘海长中文的连续 fragment window。最新语义段现在按顺序显示最后两个 fragments，若还有更早内容显示 `…`；历史段继续只显示最后一个 fragment。SwiftUI 的宽度与中文行数预留改用同一 window，避免只计算一个 fragment 却绘制多个。完整语义记录、IPC、ASR、翻译、文稿和玻璃模式均未改变。新增 SwiftPM `PlannerTests` target，并更新 Python contract 为正式 target；`swift run PlannerTests`、release `RealtimeNotchHelper` 构建与 `./tools/run_tests.sh` 475 项通过。仍需要 macOS 实机确认 1/2/3 条模式与全屏视频下的实际高度。

- `notch display planning`：确认长中文在原生刘海只显示最后一句的原因是 Swift 展示层无条件取 `latestDisplayFragment`，并非翻译、文稿或 segment state 丢失。新增 `NOTCH_LONG_TRANSLATION_DISPLAY_PLAN.md`：active cue 将显示有界、连续的最近两个 fragments，history 保持单 fragment；要求展示选择、尺寸计算与实际渲染共用同一模型。此条只记录设计，未改运行行为。

- `Parakeet reliability`：实施候选段与 native-final 对账的 Phase 0–2。仅 Parakeet 的 host semantic boundary 现在先成为候选，经历两次不同 stable observation 且至少 350 ms 后才 seal；未 seal 前不会触发 Smart Hint、远程 Final 或永久文稿。native source-final 改写同段词时复用 segment ID，以 `source_correction` 触发覆盖；SegmentStore 清空旧译文并拒绝旧 source 的远程回写，Pipeline 原位替换 finalized context，避免重复 Smart Hint。范围限同段、token 数不变的替换；未改 EOU debounce、模型/音频路径或 Apple/MLX。新增 Coordinator、SegmentStore 与 Pipeline contract 回归；`./tools/run_tests.sh` 通过 472 项。仍需要 Phase 3 回放实验与 Phase 4 macOS 真实系统音频验收。

- `Parakeet control`：控制中心 ASR 页新增仅 Parakeet 可见的 EOU 去抖档位（320 / 480 / 640 / 800 ms）；保存后下一次 Launch 传给 native helper，默认与原行为一致的 640 ms。增加面板、配置保存与 transcriber 参数校验测试；Swift release helper 编译和 `./tools/run_tests.sh` 475 项通过。未改变 Apple/MLX 或自动选择策略。

- `Parakeet planning`：新增 `PARAKEET_RELIABILITY_PLAN.md`。计划先建立 host semantic boundary 被 native source-final 改写的回归安全网，再实施候选段/seal 与同 ID revision 对账，最后才做 `eouDebounceMs` 320/480/640/800 的受控实验。此条只新增计划与交接链接，未改 ASR、翻译或展示运行行为。

- `maintenance`：新增 `MAINTENANCE_PROTOCOL.md`，明确每个开发批次的记录、测试、实机验收与交接更新规则；`AGENT_HANDOFF.md` 的 PySide6 测试命令和 468 项测试基线已同步。未写入用户本机配置、日志、密钥或课堂文本。

- `presentation`：修复“初始玻璃模式下双击字幕无法切换物理刘海”。此前工厂直接创建 `OverlayWindow` 并禁用 `allow_notch_switch`；现在玻璃与刘海均由 `NativeNotchOverlay` 持有，玻璃作为可逆 delegate，因此双击、模式按钮和右键菜单都回到现有的原生刘海控制链。系统音频的玻璃透明展示参数继续保留。新增工厂、初始玻璃 delegate 与玻璃切换信号测试；`./tools/run_tests.sh` 通过 468 项，仍需要 macOS 实机确认双击字幕正文、模式按钮、右键菜单和全屏视频场景。

## 2026-08-13

- `ASR event pipeline` Phase 0/1：新增独立的 `asr_pipeline` 协议、接受闸门、streaming adapter 和 `ASRSubtitleCoordinator`。Apple 的现有 stable-prefix、语义分句、pause boundary 和 segment 编号已迁入统一协调器；Apple 草稿、Preview、Final、翻译队列、显示和记录仍由 Pipeline 持有，未改变速度优先路径。Dashboard Launch generation 已传递到 ASR session。Apple / Parakeet native helper 增加 process-generation guard，避免 reset 后旧 stdout 回调泄漏进新句。完整 PySide6 测试通过；60 秒真实系统音频 Apple smoke 测到 6 个 native final / 573 个字幕更新、无 Pipeline error。下一步仅迁移 Parakeet，再迁移 MLX；禁止重新引入旧字幕旁路。

- `ASR event pipeline` Phase 2：Parakeet EOU 保持同一 coordinator 入口。实测证明连续系统音频的 EOU 基本不触发（95 秒 374 partial / 0 EOU；切为 160 ms 输入仍无改善），因此仅对 Parakeet 加保守 host semantic boundary：稳定句末/软边界优先，长 stream 才在内容词之间切，拒绝依赖从句和功能词边界。120 秒实测从单段数百词变为 21 个 11–25 词 final、最长活动段 40 词；pause/resume 后 segment ID 单调递增、无旧句黏连。Apple 与 MLX 语义不变。

- `ASR event pipeline` Phase 3：MLX rolling buffer 现通过 `RollingASRAdapter → ASRHypothesis → ASRSubtitleCoordinator` 进入唯一字幕链。音频快照提交瞬间冻结 `sequence` 与 `audio_anchor`，旧推理晚返回不能回退新英文；VAD / 硬时长 final、pause / resume 均通过统一 boundary 处理，暂停会失效旧快照并从新 stream 起句。没有改 MLX 模型、rolling buffer、单 worker、VAD 或翻译热路径。新增真实 Pipeline contract；完整 PySide6 测试 465/465，捕获音频回放产生 7 个 ASR partial、2 个 ASR final、7 个 Apple draft、2 个 Apple final，覆盖两个 segment、无 Pipeline error。Whisper/FunASR 保持 legacy path，未随此次重构改变。

- 新增 `UNIFIED_ASR_EVENT_PIPELINE_PLAN.md`：记录 Apple / Parakeet EOU / MLX Whisper 只统一 ASR 后事件语义、而不强制统一模型表现的重构边界。计划引入 `ASRHypothesis`、`ASRStreamBoundary`、`session_generation`、`stream_id` 和音频快照顺序 `sequence`，以消除 MLX 旧字幕旁路与 Parakeet 连续语音累积问题；本文档本身不改运行代码。

- `93233d5`：修复 Pipeline contract 测试夹具兼容性。`_segment_state_store()` 只从实例字典读取启动设置，避免未初始化的 `QObject` 测试对象触发 Qt 父类异常。完整测试恢复为 414/414。
- `6103c76`：产品路线改为 macOS 优先、iPhone/iPad 延期；明确不购买 PyQt6，近期方向是 PySide6。
- `9a163be`：新增受邀体验者指南、产品发布路线和 `tools/release_audit.py`。发布扫描只检查 Git 跟踪文件，永不打印匹配到的密钥。
- `codex/pyside6-migration` M1：新增唯一 Qt 绑定边界 `ui/qt.py`；`api_test_controller`、后台 workers、字幕显示调度器、全局快捷键和应用图标模块改为只经该边界导入 Qt。主分支运行行为未改。
- M1 测试安全网：Dashboard 工作流测试改为显式无密钥配置，不再读取开发者的 `config.ini` / Keychain；新增绑定边界静态测试。完整回归为 416/416，PySide6-only 导入烟测通过。
- `codex/pyside6-migration` M2：通用下拉控件、Audio、ASR 和快捷键设置控制器均接入 Qt 绑定边界。没有改动 Carbon 热键实现、权限流程、音频采集或实时翻译。
- `codex/pyside6-migration` M3：单实例应用壳和完整 Dashboard 均改经 `ui/qt.py` 导入 Qt；M3 保持为两次独立提交，未改控制中心生命周期或业务逻辑。完整回归为 420/420。
- `codex/pyside6-migration` M4：Pipeline 的 Qt 对象和信号改经 `ui/qt.py` 导入。此项只替换绑定 API，不修改音频、ASR、Apple 草稿、Preview、Final 或模型路由；PySide6 的完整运行烟测继续等待玻璃/刘海模块迁移，避免混用 Qt 绑定。
- `codex/pyside6-migration` M5a：Swift 刘海 helper bridge 的 QObject、QTimer 和信号接入 Qt 绑定边界；IPC、三档刘海投影、短片段隐藏和自动收缩均未改动。玻璃窗口作为独立高耦合提交继续迁移。
- `codex/pyside6-migration` M5b：玻璃字幕窗口的 widgets、布局、几何、设置、计时器和信号接入 Qt 绑定边界；字幕布局、滚动跟随、40 条可见投影、全屏置顶与 macOS 原生处理均未改动。
- `codex/pyside6-migration` M6：审计确认桌面主路径直接使用 `dashboard.py`；旧 Launcher、旧 Settings Window 和旧 Hotkey Agent 不在上课启动路径。三者只完成机械 Qt 导入迁移，以保持单一绑定闭环；不启用、不删除、不改 Control+S 行为。
- `codex/pyside6-migration` M7 准备：测试也不再直接导入 Qt binding；在所有生产/测试代码均经边界后，才允许切换依赖声明与 `ui/qt.py` 的单次原子提交。
- `codex/pyside6-migration` M7：绑定边界和 requirements 已原子切换为 PySide6；没有添加 PyQt6 fallback。主分支继续保持用户正在使用的 PyQt6 稳定版，待独立实机验收后再决定是否合并。

## 运行不变式

- 用户当前通过项目 `.venv`（Python 3.12）运行；不要用系统 Python 3.9 作为完整测试依据。
- 全量测试命令：`./.venv/bin/python -m unittest discover -s tests -q`。
- 发布前扫描：`python3 tools/release_audit.py .`。
- 界面相关测试会输出 Qt headless 警告，测试通过时不代表真实 macOS 全屏、权限和 Mission Control 已覆盖。
