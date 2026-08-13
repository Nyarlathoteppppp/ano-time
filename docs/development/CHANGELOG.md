# 面向后续开发的近期变更

这里只记录对后续开发判断有帮助的事实，不复制完整 Git 日志。

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
