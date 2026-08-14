# 原生刘海传输可靠性计划

状态：**自动化实现与回归已完成；等待 macOS 实机验收。**

## 实机事实

2026-08-14 的 Diagnostics 显示 ASR / 翻译事件持续产生，Qt 玻璃字幕可
正常更新；原生 `RealtimeNotchHelper` 存活甚至重启后，刘海仍可能停在旧帧
或不显示。故障边界是 Python bridge 到 Swift helper，不是 ASR、翻译或
`SubtitleDisplayScheduler`。

## 目标与不变式

- 每个 helper 生命周期必须先发 `ready`，Python 才发送完整当前快照。
- 每个 Python frame 带 helper `generation` 和严格递增 `frameId`；Swift
  只应用更新的 frame，不能让旧任务回写新字幕。
- Swift 应用后发 `applied` 回执；Diagnostics 可追踪 send / write / applied /
  drop / restart。
- helper 退出、pipe 失败或切换回刘海时，Python 必须重启并重放最新完整
  语义投影；不能依赖已失效的 `_last_native_items` 缓存。
- 字幕内容更新与 notch 展开动画解耦。状态帧绝不重复触发展开；内容从
  compact / hidden 转为可见时最多启动一次转换。
- 完整 semantic record、玻璃 delegate、翻译调度和文稿不改变。

## 实施与验收

1. Python bridge 已将 latest-only queue 改为带 generation 的 frame envelope，
   并在 Qt 主线程安全地处理 helper 的 `ready` / `applied` / 异常退出。
2. Swift 输入协议已加入 frame order gate；应用状态后立即 ack，不等待动画。
3. 已提取/测试纯 Swift frame ordering，并为 Python snapshot replay、旧
   generation drop、ready 重放、status snapshot、当前 helper pipe failure
   recovery 调度与 ack 状态建立回归测试。Python
   targeted tests 53 项通过；`swift run --package-path native_notch
   PlannerTests` 与 release helper 编译通过。
4. 待手工验收：播放连续课堂音频 60–120 秒，至少执行 notch → glass → notch
   两次、暂停/恢复一次、长中文一次。Diagnostics 中每个最新 send 都应有
   同 generation 的 applied；玻璃与刘海不允许各自停在不同旧句。

## 非目标

本计划不改变 fragment window 数量、ASR 模型、Apple 草稿、翻译 provider
或展示政策。长中文的内容窗口规则仍由
`NOTCH_LONG_TRANSLATION_DISPLAY_PLAN.md` 约束。
