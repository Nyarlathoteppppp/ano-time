# 刘海长中文译文展示修复计划

状态：**Phase 0–2 已实施并通过自动验证；Phase 3 的 macOS 实机视觉验收待完成。**

关联实现：`native_notch_overlay.py`、
`native_notch/Sources/SubtitlePresentation/NotchPresentation.swift`、
`native_notch/Sources/RealtimeNotchHelper/main.swift`。

## 缺陷事实

长中文译文在 Python 侧已被保留为一个完整 semantic record，并按宽度拆成有序的 `fragments`。该拆分不影响文稿、远程 Final、SegmentStore 或玻璃窗口。

Swift 原生刘海当前对每个语义 cue 都调用 `latestDisplayFragment`。因此一条长中文即使有多个 fragments，屏幕也只画最后一个；截图中的“这是一个快速交付”是最后 fragment，并不是翻译只返回了这一句。

## 目标

当前活跃语义段必须显示连续的中文上下文，而不是孤立的末尾 fragment；历史段保持紧凑。修复后用户仍能在 1 / 2 / 3 条刘海模式间切换，且不会把显示 fragments 写进文稿或改变实时链路。

## 不变量

- `SubtitleRecordStore` 仍只保存完整 source / translation；展示 fragments 不能进入文稿或导出。
- `segmentID`、翻译 revision、Apple 草稿、AI Preview / Final、Smart Hint、ASR 与 provider 路由均不变。
- 同一语义段的 revision 必须原位更新，不能被看作新句触发 roll-up 动画。
- 长文本不能使刘海无限增高；展示只保留有界的最近上下文。
- 玻璃模式继续显示完整语义记录，不采用刘海的 fragment window。

## 设计：活跃段连续窗口，历史段单片段

Python 继续提供完整 ordered `fragments`。Swift 新增纯展示选择规则：

| cue 角色 | 渲染内容 | 目的 |
| --- | --- | --- |
| active（最新 semantic segment） | 最后两个 fragments，按原顺序 | 保留最近两段连续中文，而非只看见一句尾巴。 |
| history（已滚入历史） | 最后一个 fragment | 避免 2 / 3 条模式无限增高。 |
| 无 fragments 的兼容消息 | 原有单行内容 | 保持旧 IPC / fallback 行为。 |

若 active cue 有三个或更多 fragments，在窗口开头显示轻量 `…`，明确前文仍存在但因刘海空间未展开。每个显示 fragment 继续携带配对的英文、中文、finalized 和 committed-prefix 信息；不混合不同 `segmentID` 的文本。

为保证窗口有可读长度但仍受控，第一版只增加 active cue 的一个额外 fragment，不增加 Python 的切分频率、EOU、ASR 分段或翻译请求。必要时再根据实机高度调整“两个 fragment”的常量；不在本次把它变成用户设置。

```text
完整译文 [片段 1] [片段 2] [片段 3] [片段 4]
                         │          │
历史 cue                 └──只显示片段 4
当前 cue                    显示 … + 片段 3 + 片段 4
```

## 2026-08-14 实施记录

- `NotchCue.displayWindow(for:)` 已成为纯展示选择边界：active 保留按原顺序排列的两个末尾 fragments，超过两个时返回 `hasHiddenPrefix`；history 和无 fragments 的兼容消息都保持单条。
- `SubtitleCueView` 直接渲染该 window，前缀省略以 `…` 提示；不再把 `latestDisplayFragment` 当作 active cue 的唯一内容。
- 宽度估算和中文行数预留改用同一 window 的全部 fragments，避免视觉绘制比几何预留多一段而被裁剪。
- 已新增 Swift PlannerTests target，且 Python contract 覆盖了 fragment IPC 的语义单一性、顺序和 Swift 选择边界。
- 未改 Python semantic record、IPC schema、ASR、翻译、文稿、玻璃模式或任何 provider 配置。

## 实施步骤

### Phase 0 — 先建红色回归（已完成）

1. 在 `native_notch/PlannerTests/main.swift` 为 active / history fragment window 建立纯 Swift 断言：active 保留最后两个且顺序不反转，history 只保留最后一个，无 fragments 时回退单条。
2. 在 `tests/integration/native_helpers/test_native_notch_source_contract.py` 检查运行 helper 不再以 `latestDisplayFragment` 作为 `SubtitleCueView` 的唯一输入。
3. 在 `tests/unit/subtitles/test_native_notch_overlay.py` 保留现有“长译文仅一个 semantic record”的断言，并补 IPC 顺序断言，确保 Python 端不被错误修改。

### Phase 1 — 在展示模型选择 fragment window（已完成）

在 `SubtitlePresentation` 增加与 SwiftUI 无关的 `NotchCue` / `NotchCueSlot` 展示选择 API。该 API 接收 cue role，返回有界 `NotchFragment` 列表及是否需要 context marker。不要把选择规则放到 `SubtitleCueView` 内，避免尺寸计算与实际绘制再次不一致。

### Phase 2 — 用相同窗口驱动绘制与布局（已完成）

1. `SubtitleCueView` 接收 selected fragments，以稳定 fragment ID 渲染；active 的两个 fragment 按时间顺序连续显示。
2. `SubtitleState.visibleRows()`、宽度测量、中文行数预留都改用同一份 selected fragments，而非所有 cue 的 `latestDisplayFragment`。
3. 维持 `.transition(.identity)` 与既有 revision-run 高亮；文本修订只更新相同 cue / fragment，不触发整行移动。
4. 展示窗口变化导致的扩张立即发生；收缩继续用已有 cooldown，避免 partial 修订时刘海呼吸。

### Phase 3 — 构建与验收（自动完成；macOS 实机待验）

自动验证：

```bash
cd native_notch && swift run PlannerTests
./.venv-pyside/bin/python -m unittest tests.unit.subtitles.test_native_notch_overlay tests.integration.native_helpers.test_native_notch_source_contract -v
./tools/run_tests.sh
git diff --check
./.venv-pyside/bin/python tools/release_audit.py .
```

macOS 实机验收：

1. 让一条中文草稿增长到至少 3 个 fragments：当前段应显示 `…` 与连续的两个末尾 fragment，不能只剩最后一句。
2. 接收 AI Final：同一 `segmentID` 原位替换，不能额外滚入历史或闪空。
3. 分别检查刘海 1 / 2 / 3 条模式：当前段连续、历史紧凑、没有英文/中文跨 segment 配对。
4. 切到玻璃后，完整中文仍在对应 semantic record；切回刘海后继续采用窗口，不丢文稿。
5. 在全屏视频、pause/resume 与 `Control + S` 后重复一次，确认 helper 重启不会恢复旧 fragment window。

## 明确不做

- 不改变 `max_chars=58`、ASR host boundary、Parakeet EOU debounce 或翻译 provider。
- 不将整段无限长中文直接塞进刘海，也不以 timer 滚动全文。
- 不把 fragment 当独立句子、独立 `segmentID` 或独立文稿条目。
- 不修改 `AnoTime-macOS`。

## 回滚边界

如果 active 两片段导致刘海在 2 / 3 条模式遮挡课堂内容、revision 出现跨 fragment 闪烁，回滚仅限 Phase 1/2 的 Swift 展示选择；Python semantic record、IPC payload 和实时翻译链均保持不动。
