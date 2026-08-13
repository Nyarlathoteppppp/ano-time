# 统一 ASR 事件管线：设计与迁移计划

> 状态：Phase 0、Phase 1、Phase 2、Phase 3 已完成并验证。
> 范围：Apple Speech、Parakeet EOU、MLX Whisper 在 **ASR 输出之后** 的统一事件语义。  
> 非目标：不重写任一 ASR 模型；不改变 Apple 草稿的速度优先策略；不改模型路由、课程档案、Smart Hint 或刘海视觉设计。

## 1. 问题与目标

AnoTime 现在有三个本地 ASR 后端，但只有 Apple Speech 完整经过当前实时字幕状态机。

```text
Apple Speech
  native partial / native final
  → 稳定前缀 → 分句 → Apple 草稿 → Preview / Final
  → SubtitleEvent → 刘海 / 玻璃 / 记录

Parakeet EOU
  partial / 很少出现的 EOU final
  → 已进入上述路径，但长时间连续语音时会累积为很长的一段

MLX Whisper
  rolling buffer → RollingASRAdapter → ASRHypothesis
  → 稳定前缀 → 分句 → Apple 草稿 → Preview / Final
  → SubtitleEvent → 刘海 / 玻璃 / 记录
```

目标不是让三个模型的首字延迟、改写频率或 native final 完全一样。那既不现实，也会损害各自优势。

目标是：**不同模型只负责产生英文；英文进入产品后必须经过唯一的字幕状态机。**

```text
Apple adapter ───┐
Parakeet adapter ├─→ ASR event protocol → ASRSubtitleCoordinator
MLX adapter ─────┘                         │
                                           ├─ stable prefix / semantic segments
                                           ├─ Apple draft / Preview / Final
                                           └─ SubtitleEvent
                                                ├─ Notch presentation
                                                ├─ Glass presentation
                                                └─ Transcript recording
```

## 2. 不变式

以下规则是这次改动的验收基线。

1. Apple 的 `ASR partial → Apple Translation draft` 不等待任何远程请求、记录写入、诊断或 UI 动画。
2. 切换 ASR 后端只替换英文输入来源；不允许绕过 Apple 草稿、AI Preview、Final、记录和显示模式。
3. ASR 后端不得直接创建 `segment_id`、`SubtitleEvent`、远程翻译任务或 UI 对象。
4. 任何晚到、旧会话、旧音频 buffer 的识别结果都不得回退当前字幕。
5. `ASR source final`、`semantic segment`、`display fragment` 是三个不同概念，不能混用。
6. 展示层永远是下游消费者；刘海/玻璃布局不能反向控制 ASR、分句或翻译调度。
7. 改动期间 Apple 行为必须先保持等价，再接入 Parakeet、MLX；不得同时迁移三条路径。

## 3. 三层边界

### 3.1 ASR source final

这是模型或音频端声明“这段输入已结束”的事实：

- Apple Speech 的 native final；
- Parakeet 的 EOU；
- MLX 在 VAD、硬时长限制或暂停边界收到的最终 buffer；
- 用户暂停、停止时的显式边界。

它不自动等价于一条完美的自然语言句子。

### 3.2 Semantic segment

这是产品能够安全地：

- 分配新的 `segment_id`；
- 发起 Final 远程精修；
- 写入完整课堂记录；
- 加入后续翻译的 finalized context；
- 允许下一句从一个新的语义状态开始。

语义段优先使用明确句末、原生 final 和可靠的稳定边界。不能为了避免长字幕而在 `because`、`of`、`which` 等依赖结构后把文本假装定稿。

### 3.3 Display fragment

这是仅为了当前屏幕可读性切出的显示片段。例如一条很长、尚未语义定稿的 Parakeet partial 可以被刘海拆成两行或局部片段。

Display fragment：

- 不创建新的语义 `segment_id`；
- 不进入远程 Final context；
- 不写成独立课堂记录；
- 不触发新的模型请求；
- 可以在同一 segment 内随 partial 更新。

现有 `DisplayFragmentPlan` 和展示层布局继续负责此层；这次不让 ASR adapter 自己处理窗口换行。

## 4. 统一事件协议

新增纯领域模块，建议放入 `asr_pipeline/`。该包不能导入 Qt、PySide6、网络 client、Provider Router、Dashboard 或原生 Swift helper。

```text
asr_pipeline/
├── __init__.py
├── events.py          # 不可变 ASR 事件与枚举
├── acceptance.py      # stream / sequence 过期拒绝规则
├── coordinator.py     # ASRSubtitleCoordinator
└── adapters.py        # streaming / rolling 协议适配；不拥有模型生命周期
```

现有低层模型实现不搬动：

```text
apple_transcriber.py       # 仍管理 Apple RecognitionTask
parakeet_transcriber.py    # 仍管理 Swift / FluidAudio helper
transcriber.py             # 仍管理 MLX rolling inference
```

### 4.1 `ASRHypothesis`

建议协议如下。字段名可在实现时微调，但语义不能减少。

```python
@dataclass(frozen=True, slots=True)
class ASRHypothesis:
    text: str
    source_final: bool
    backend: ASRBackend            # apple / parakeet_eou / mlx
    session_generation: int        # 每次 Launch / resume 边界递增
    stream_id: int                 # 当前连续语音流，边界后递增
    sequence: int                  # 此 stream 内、按音频快照顺序递增
    audio_anchor: float | None     # 单调时钟；对应这段语音开始
    emitted_at: float              # 单调时钟
```

协议保证：

- `text` 是当前 `stream_id` 的**累计英文假设**，不是差异文本；
- `sequence` 必须在**音频快照提交时**分配，而不是模型完成时分配；这样 MLX 的旧 buffer 即使晚返回，也保留较小编号；
- `stream_id` 只在明确音频边界后递增，不随每个 partial 递增；
- `source_final=True` 表示该假设是当前 stream 的最终来源输出，不表示必然已是新的语义句；
- adapter 必须先清理空白，但不得做课程术语纠错、翻译、分句或 UI 裁剪。

### 4.2 `ASRStreamBoundary`

文本为空但需要断开状态时使用单独事件：

```python
@dataclass(frozen=True, slots=True)
class ASRStreamBoundary:
    backend: ASRBackend
    session_generation: int
    stream_id: int
    sequence: int
    reason: BoundaryReason  # pause / stop / vad_silence / reset / source_reset
    audio_anchor: float | None
```

用途：暂停/恢复、VAD 静音、后端 reset、停止时没有可用尾文本的情况。它避免通过伪造空字符串 `final` 来重置分句器。

### 4.3 接受闸门（Acceptance Gate）

`ASRSubtitleCoordinator.accept(event)` 的第一步不是分句，而是判断事件是否还属于当前可见会话。

```text
session_generation 较旧   → 丢弃
stream_id 较旧            → 丢弃
同 stream 的 sequence 较旧 → 丢弃
同 sequence 的重复内容     → 去重
其余                       → 进入共同状态机
```

这个闸门早于现有 `SubtitleEvent.revision`。后者仍保留，用于已经进入字幕状态库之后的 Apple / AI 结果拒绝；两者职责不同。

| 字段 | 解决的问题 |
| --- | --- |
| `session_generation` | pause / stop / Launch 后旧线程回调覆盖新字幕 |
| `stream_id` | 前一句 buffer 黏连到下一句 |
| `sequence` | MLX 旧音频快照晚完成后让英文回退 |
| `SubtitleEvent.revision` | 同一句的 Apple / Preview / Final 旧翻译结果覆盖 |

## 5. `ASRSubtitleCoordinator` 的职责

新组件命名为 `ASRSubtitleCoordinator`，避免与现有只负责渲染节奏的 `SubtitlePresentationCoordinator` 混淆。

它接收标准事件，复用当前 Apple 原生路径中成熟的逻辑：

```text
ASRHypothesis
  → 接受闸门
  → StablePrefixTracker
  → IncrementalSegmenter
  → 语义 segment 状态（segment id / remainder / revision）
  → ASR_PARTIAL / ASR_FINAL SubtitleEvent
  → FastPath Apple partial / Apple final
  → ProgressiveTranslationPreview
  → Final remote scheduling
```

它通过依赖注入持有回调，而不是导入 UI：

```python
ASRSubtitleCoordinator(
    emit_subtitle=...,                # Pipeline._emit_subtitle
    submit_fast_partial=...,          # FastPath / existing executor wrapper
    submit_fast_final=...,            # FastPath / existing executor wrapper
    preview_service=...,              # ProgressiveTranslationPreview
    schedule_final_remote=...,        # existing final scheduler
    snapshot_final_context=...,       # existing ContextPolicy wrapper
    apply_final_asr_corrections=...,  # existing profile correction service
    on_runtime_status=...,            # signal wrapper
    on_diagnostic=...,                # optional log_stage wrapper
)
```

因此它不拥有：音频 generator、线程池生命周期、ASR 模型实例、Qt signal、Provider client、OverlayWindow、Native notch helper。

`Pipeline` 仍负责每次 Launch 的资源所有权：创建 audio / ASR runner / FastPath / executors / preview service，停止时按原顺序关闭它们。

## 6. 后端 Adapter 的职责

Adapter 是薄协议转换层。它不能包含翻译判断、字幕展示判断或模型路由。

### 6.1 Apple adapter：基准实现

```text
AppleSpeechTranscriber callback(text, final)
  → AppleASRAdapter
  → ASRHypothesis
  → ASRSubtitleCoordinator.accept(...)
```

迁移第一阶段必须做到“行为等价”：只把当前 `_processing_loop_apple()` 的 `on_result` 状态机移入 Coordinator。Apple 的 FastPath 调度、stable-prefix 参数、段落阈值、日志字段和停顿/暂停行为不重新设计。

### 6.2 Parakeet adapter：EOU 不等于字幕分句

```text
FluidAudio partial callback
  → ParakeetASRAdapter → source_final=False

FluidAudio EOU callback
  → ParakeetASRAdapter → source_final=True
```

Parakeet 在连续课程语音中可能很久不产生 EOU。基准测试中，一段 89.65 秒连续音频只有一个 native final。因此不能把“收到 EOU”作为字幕可读性的唯一来源。

策略：

1. 每个 Parakeet partial 都进入共同 Coordinator，英文、Apple 草稿和 Preview 保持持续更新；
2. `StablePrefixTracker` 继续发现已确认文字；
3. 只有明确句末、EOU/真实音频暂停、或保守安全边界才产生 semantic segment；
4. 连续无 EOU 且无安全语义边界时，交给 `DisplayFragmentPlan` 做**显示级**切分，绝不伪造 Final；
5. 后续 EOU/native final 仍是最终纠错权威，可修正未确认尾部。

这样 Parakeet 不会再把一整段直接塞进一个字幕对象，同时不会为了好看而把从句错误写入 Final context 或课堂记录。

如果后续发现 Parakeet 原生 EOU 对系统音频确实长期不可靠，才单独评估 host VAD 生成 `ASRStreamBoundary(reason=vad_silence)`；这是独立的中风险行为调整，不能混入初始协议重构。

### 6.3 MLX adapter：保留推理，只替换出口

当前 MLX 使用 rolling audio buffer + 单一 MLX worker。这部分先完全保留。

```text
现状：
rolling buffer → MLX inference → _process_partial_chunk / _process_final_chunk

目标：
rolling buffer → MLX inference → RollingASRAdapter → ASRHypothesis
                                          ↓
                               ASRSubtitleCoordinator
```

关键细节：

- 每次 audio buffer 复制并提交时通过不可变 `RollingASRSnapshot` 分配
  `sequence` 和 `audio_anchor`；推理返回时间不参与顺序判定；
- 同一个滚动语音 buffer 持续使用同一 `stream_id`；
- VAD、硬切或暂停时，最后一个有效假设以 `source_final=True` 交给 Coordinator，随后开启新 stream；
- MLX worker 仍可维持单 worker；Coordinator 不依赖并行来正确工作；
- `_process_partial_chunk()` / `_process_final_chunk()` 已不再是 MLX 的字幕出口；
  它们暂时保留给尚未迁移的 Whisper / FunASR legacy path，不能因为 MLX
  重构而删除。

MLX 的首字延迟仍受 rolling re-transcription 本身限制；本计划只确保它获得同等的产品功能，而不承诺它变成 Apple 式 token streaming。

## 7. 保留的下游架构

统一 ASR 协调器的输出仍是已有 `SubtitleEvent`。不新建第二套显示协议。

```text
ASRSubtitleCoordinator
  → SubtitleEvent
      → SegmentStateStore / stage ordering
      → SubtitlePresentationCoordinator
      → DisplayFragmentPlan
      → Native notch (small / medium / large)
      → Glass overlay (latest 40 visible)
      → SessionTranscriptRecorder
```

当前用户可见行为必须继续成立：

- 小刘海只显示中文；中 / 大显示既有的双语层级；
- 三种刘海大小只改变投影条数，不改变语义段或翻译调度；
- 玻璃模式只保留最近 40 条可见字幕，完整 final 记录在后台保存；
- 远程 Final 的迟到结果不能抢回已经滚出的字幕；
- Stop / pause 后不把上次课程 context 和尾文本带入下一段。

## 8. 分阶段实施

每一阶段独立提交、完整测试、至少一段实际系统音频验证。任何一阶段失败只回滚该提交，不让 Apple 现有稳定链路被带坏。

### Phase 0：安全网与事件追踪（无运行行为改变）

新增纯单元测试和后端无关的 trace fixture：

```text
tests/fixtures/asr_hypotheses.py
tests/unit/asr_pipeline/test_acceptance.py
tests/unit/asr_pipeline/test_coordinator_contract.py
tests/integration/pipeline/test_asr_backend_contracts.py
```

准备 Apple 的现状轨迹：partial 增长、native final、pause/reset、Final 晚到。它是迁移后的行为基准。

验收：只新增测试和数据对象；Apple 路径没有执行变化。

### Phase 1：抽取 Coordinator，Apple 等价迁移

1. 增加 `ASRHypothesis` / `ASRStreamBoundary` / Acceptance Gate；
2. 从 `_processing_loop_apple()` 抽出当前 `on_result` 的字幕状态机到 `ASRSubtitleCoordinator`；
3. Apple callback 用 `AppleASRAdapter` 发送事件；
4. 保留 `Pipeline` 的线程、FastPath、Preview Service、日志和停止责任；
5. 将 Apple 事件轨迹与迁移前的测试结果逐项比对。

验收：Apple 的 partial/final 次序、FastPath 调用数、语义分句、Preview/Final 可见性和延迟不回归。

风险：低—中。原因是代码移动范围大，但不能修改规则；任何非等价结果立即回滚。

**实施记录（2026-08-13）**

- `ASRSubtitleCoordinator` 已接管 Apple 的 stable-prefix、语义分句、pause boundary 与 segment 编号；
- Apple 的 FastPath、Apple Translation、Preview、Final、executor 和 Qt 信号仍由 `Pipeline` 持有，未迁入 coordinator；
- Dashboard 的 Launch generation 已传入 Pipeline，作为 ASR 事件 session generation；
- Apple 与 Parakeet 原生 helper 现在各自带有 process generation guard，旧 helper stdout 即使在 reset 后残留，也不能进入新会话；
- 自动测试通过，实际系统音频 smoke test 连续识别到 6 个 Apple native final、573 个字幕更新，未出现 Pipeline error；
- 烟测中的 Apple Translation 一次曾报 `Unable to Translate`，另一次恢复 Ready；它是 macOS 翻译资源状态，不属于 ASR 协调器或事件协议回归。

### Phase 2：Parakeet 接入与长连续语音验证

1. 通过 `ParakeetASRAdapter` 接入同一 Coordinator；
2. 保持 EOU 为 `source_final`，不把它当作唯一分句来源；
3. 对无 EOU 长语音验证显示 fragment 仍受控；
4. 对真实 EOU / 停顿验证 semantic final、上下文、记录和下一段正确衔接；
5. 不改 Parakeet Swift helper 的模型、160 ms chunk、EOU debounce 或计算设备。

验收：至少 90 秒连续系统音频；不出现整屏单 segment、不重复 Final、不丢 Apple 草稿；语义记录不被显示级碎片污染。

风险：中。风险集中在边界过于激进时破坏语义，因此初版只使用现有保守分句规则。

**实施记录（2026-08-13）**

- 95 秒系统音频基准确认 Parakeet 可产生 374 个 partial、0 个运行中 EOU；最长一个 open segment 为 306 词。50 ms 与 160 ms 输入块均没有改善运行中 EOU，因此不以 helper input size 作为修复方案；
- 只为 `parakeet_eou` 开启 `IncrementalSegmenter` 的 host policy：优先稳定句末、软边界和显式语篇起点；连续长语音达到受控窗口后，只允许在两个内容词之间切，避开冠词、介词、连接词、助动词及 `because` / `if` / `so that` 等依赖结构；
- 120 秒实测得到 21 个约 11–25 词的 semantic final，最长活跃 partial 为 40 词；没有 Pipeline error；
- 67 秒 pause/resume 实测中，恢复后的 segment ID 从 6 开始，未出现旧 ID 或旧尾文本黏连；
- 该 policy 不对 Apple 或即将迁移的 MLX 生效。它确实以有限句法猜测换取 Parakeet 可用的远程 Final / 记录边界，因此仍保持 experimental 标识。

### Phase 3：MLX 出口迁移

1. 为 audio snapshot 提交处建立 `sequence` / `audio_anchor` 分配；
2. 将 MLX partial 和 VAD final 转换成统一事件；
3. 删除 MLX 到旧 `_process_partial_chunk()` / `_process_final_chunk()` 的字幕调用；
4. 保留 rolling buffer、MLX 单 worker、VAD 参数和 ASR 本体；
5. 在新 contract 覆盖后才删除不再使用的旧路径。

验收：MLX 可使用所有刘海大小、玻璃模式、分句、Apple 草稿、Preview、Final、记录；旧 buffer 晚回来不会倒退；暂停后不黏连。

风险：中。MLX 的输出时序与 Apple 不同，必须验证 `stream_id / sequence` 的边界而非只看单句结果。

**实施记录（2026-08-13）**

- `RollingASRAdapter` 在音频快照进入原有单 worker 前冻结
  `session_generation / stream_id / sequence / audio_anchor`。旧推理即使较晚完成，
  也会由接受闸门按快照顺序拒绝，不能使字幕英文回退；
- rolling buffer、MLX 模型、单 worker、VAD 阈值、音频更新间隔和推理参数均未改变。
  VAD / 硬时长的 source final 仍通过同一 worker 串行提交；空 VAD 结果变为
  `ASRStreamBoundary(VAD_SILENCE)`，不会越过先前已排队的 partial；
- pause 会使 adapter 递增 submission epoch、密封当前可见 stream，并丢弃仍在
  推理中的旧快照。恢复后只能从新的 stream 开始，避免旧尾文本黏连；
- MLX 的 partial / final 现在与 Apple / Parakeet 共用
  `ASRSubtitleCoordinator`，因此统一获得 stable prefix、semantic segment、
  Apple 草稿、AI Preview / Final、显示投影和课堂记录；
- 新增 MLX rolling contract tests。完整 PySide6 套件为 465/465；使用已捕获的
  系统音频回放实测，MLX 产生 7 个 ASR partial、2 个 ASR final、7 个 Apple partial
  与 2 个 Apple final，覆盖两个连续 segment，未出现 Pipeline error；
- Whisper / FunASR 仍保持 legacy path，明确不属于本阶段；后续若迁移，必须先建立
  相同的 adapter contract 与真实音频回归，禁止直接复制 MLX 逻辑。

### Phase 4：收尾与文档

1. 清理迁移后不再可达的旧 MLX 字幕代码；
2. 将支持矩阵写入控制中心和 README：Apple 为默认；Parakeet / MLX 为实验性本地 ASR；
3. 更新 `docs/AGENT_HANDOFF.md` 的运行路径与测试数；
4. 保存 Apple / Parakeet / MLX 的同音频对比，不把私人课堂内容提交到 Git。

风险：低。只在三条路径通过实机验收后进行。

## 9. 测试矩阵

### 9.1 纯单元测试

| 测试 | 关键断言 |
| --- | --- |
| Acceptance Gate | 旧 session、旧 stream、旧 sequence 被拒绝；重复事件去重 |
| Stable Prefix | 累计 partial 的稳定前缀单调推进 |
| Segmenter | source final 可提交尾部；partial 不伪造不安全 semantic final |
| Display fragments | 长 partial 可读，但不创建新 semantic segment |
| Context | 只有 semantic final 进入 finalized context；display fragment 不进入 |
| Pause boundary | 恢复后新 stream，旧 remainder 不泄漏 |

### 9.2 后端 contract tests

对 Apple、Parakeet、MLX 的模拟 event trace 使用同一断言：

```text
ASR_PARTIAL
→ Apple partial draft
→ optional preview
→ ASR_FINAL / semantic final
→ Apple final + remote Final
```

允许阶段到达时机不同，不要求文字完全一致。验证的是：

- 不倒退；
- 只有一个下游状态机；
- 旧事件不能覆盖；
- 记录与上下文只接收语义 final；
- 展示模式只消费 `SubtitleEvent`，不读取 backend。

### 9.3 实机验证

每个后端至少跑 60–120 秒系统音频，Apple/Parakeet 的连续语音测试建议 90 秒以上。

检查：

```text
小 / 中 / 大刘海
玻璃 ↔ 刘海切换
Apple 草稿持续出现
远程 Preview 超时不阻断 Final
暂停 → 恢复不黏连
停止后无残留 helper / worker
不会写入课堂记录的重复 display fragment
```

性能记录仅在 Diagnostics 开启时写入；正常上课不能因为本次重构新增同步磁盘 I/O。

## 10. 明确不做的事

本计划不包含：

- 改变 Apple Speech / Apple Translation 的调用频率；
- 为追求视觉平稳而节流 Apple partial；
- 让 Parakeet/MLX 强行匹配 Apple 的首字速度；
- 加入云 ASR、Whisper.cpp、Moonshine 或新模型；
- 修改 AI Prompt、上下文预算、Smart Hint、课程档案或 Provider quota；
- 把显示 fragment 写入语义上下文；
- 为测试而调用真实远程模型、真实 Keychain 或真实课堂资料。

## 11. 完成定义

本重构完成时，以下条件必须同时满足：

1. Apple、Parakeet、MLX 均通过 `ASRHypothesis → ASRSubtitleCoordinator` 进入字幕链；
2. 不存在 MLX 专用的旧字幕旁路；
3. 三个后端均支持既有小/中/大刘海、玻璃、Apple 草稿、Preview、Final、记录和暂停边界；
4. Parakeet 无 EOU 的长连续讲话不会把整个课堂塞进单一可见 subtitle；
5. sequence / stream / session 过期保护覆盖 MLX buffer、暂停恢复和停止后回调；
6. Apple 实测延迟与迁移前基准等价；
7. 所有自动测试和对应实机测试通过，且每阶段可独立回滚。

## 12. 决策记录

| 决策 | 结论 |
| --- | --- |
| 是否让后端表现完全一致 | 否；统一产品事件语义，不统一模型时序或文字 |
| 是否只用 `is_final` | 否；使用 `source_final`，并单独表达 semantic segment / display fragment |
| 是否加入 `sequence` | 是；在 MLX 音频快照提交时分配 |
| 是否加入 `stream_id` 与 `session_generation` | 是；解决暂停、重启、buffer 回调的边界污染 |
| Parakeet 无 EOU 时是否强制 Final | 否；先显示级切分，语义 final 保持保守 |
| MLX 是否重写推理方式 | 否；保留 rolling buffer + 单 worker，只替换字幕出口 |
| 是否改 Apple fast path | 否；Apple 是行为与延迟基准 |
