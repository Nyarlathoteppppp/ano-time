# Parakeet 连续课堂语音可靠性计划

状态：**Phase 0–2 与低音量输入预处理已通过自动回归；Phase 3 参数实验与 Phase 4 实机验收尚未完成。**

关联基线：[`LOCAL_ASR_BENCHMARK_2026-08-13.md`](../LOCAL_ASR_BENCHMARK_2026-08-13.md)、
[`UNIFIED_ASR_EVENT_PIPELINE_PLAN.md`](./UNIFIED_ASR_EVENT_PIPELINE_PLAN.md)、
[`AGENT_HANDOFF.md`](../AGENT_HANDOFF.md)。

## 目标与边界

目标是让 Parakeet 在连续英文课堂系统音频中形成可靠、可纠正的字幕段，同时保留它较快的首个英文 partial。它不是替换 Apple Speech 的项目。

- Apple Speech 继续是默认 ASR、延迟和资源基线。
- Parakeet 继续是用户显式选择的实验性英文路径；不得自动选择或作为 Apple 的 fallback。
- Apple Speech 是低音量识别对照基线，但本阶段不同时运行 Apple 与
  Parakeet：既有基准明确要求顺序运行，避免两个本地识别器竞争 CPU / ANE。
- 不改 Apple Translation、Smart Hybrid 路由、Preview/Final deadline、录音、字幕调度或 legacy Whisper/FunASR。
- 不把模型、CoreML compute、音频采集或 EOU 参数变成未验证的用户可调项。

## 已知事实

| 项目 | 当前观察 | 结论 |
| --- | --- | --- |
| 首个 token / ≥3 词 | Parakeet 0.82 s / 1.33 s；Apple 1.04 s / 1.93 s | Parakeet 的早期 partial 值得保留。 |
| 连续 89.65 秒系统音频 | Parakeet 仅一个 EOU/final；Apple 11 个自然 final | 不能只依赖 native EOU 形成课堂字幕段。 |
| 资源 | Parakeet CPU 28.1% 平均、58.8% 峰值、296 MB 峰值；Apple 1.0%/3.4%/51 MB | 不能以额外轮询或重复推理换取分段。 |
| 术语样本 | Parakeet 9/12，Apple 11/12 | 分段策略不会修复模型听错，术语准确性须单独评估。 |

当前 `IncrementalSegmenter` 只对 Parakeet 开启 host semantic boundary。host cut 先成为候选段；在两次不同 stable observation 一致且经历 350 ms 后才 seal。native source-final 仍是权威文本：同段内词替换以原 `segment_id` 发出 source correction，清除旧译文并拒绝旧远程结果回写。

## 2026-08-14 实施记录

- Phase 0：已补 host candidate、native-final `figure → model` 改写、pause/reset 隔离、SegmentStore 旧远程结果拒绝和 Pipeline 上下文替换的回归测试。
- Phase 1：仅 Parakeet host boundary 生成候选段。候选仅维持 ASR partial / Apple 草稿；未 seal 前不走永久文稿、Smart Hint 或远程 Final。seal 条件为两次不同稳定观察与 350 ms。
- Phase 2：`ASRSemanticFinal.source_correction` 使 native final 的同段词替换复用 `segment_id`。`SegmentStore` 清空旧译文并拒绝旧 source 的翻译；Pipeline 将既有上下文原位替换，避免重复 Smart Hint。
- 已知边界：当前仅处理同一候选段内、token 数不变的替换。跨候选段重切分、插入或删除 token 必须先有可复现 trace，留在后续工作中。
- 未实施：未改 EOU debounce、模型参数、CoreML compute、音频采集与 Apple/MLX 路径；尚未进行真实课堂音频验收。

用户可在控制中心选择 320 / 480 / 640 / 800 ms 的 Parakeet EOU 去抖档位；设置保存后下一次 Launch 传入 native helper。该选择是 Phase 3 的手动实验入口，不构成完成验收或自动推荐。

## 低音量输入预处理（已实施，待实机验收）

实机日志已确认：Parakeet 路径会收到每个 50/100 ms PCM block，低音量
问题不是 `silence_threshold` 丢弃音频；它是模型在安静语音下未产生文本。
Apple Speech 在相同音源下表现更稳，但不能直接把第二个识别器并行塞进
课堂路径。

因此新增的实验选项只在用户明确选择 Parakeet 后生效：在 Python →
Parakeet helper 边界做有上限的 RMS 增益。RMS ≤ 0.0015 的静音不放大；
0.0015–0.020 的弱音频提高到目标 RMS 0.035，最多 4 倍；正常音量保持不变，
输出统一限幅到 [-1, 1]。开关默认关闭，用户可在 ASR 控制中心选择；启用后
下一次 Launch 生效。Diagnostics 每两秒记录 pre-gain RMS 与实际 gain，不记录
音频内容。

实现只变更 `ParakeetEOUTranscriber.feed()` 的 helper 输入 PCM；它不改变
音频采集、用户的 silence threshold、Apple/MLX 输入或 Apple Translation。
`ParakeetAdaptiveGain` 的 silence、弱音量、正常音量与 PCM 序列化回归测试，
以及控制中心保存/显示测试已通过。

验收使用同一受许可音频的低 / 中 / 正常音量回放，对比 Apple 与
Parakeet 的首 partial、漏识别和 CPU。若归一化增加静音 hallucination、CPU
超过基线或使正常音量退化，关闭该选项；不得以调低 VAD 阈值替代此验收。

## 推荐设计：候选段 + 原生终稿对账

### 1. Host 切段不是不可逆终稿

host semantic boundary 产生 `candidate segment`，保存：稳定 token 范围、切段原因、首次/最近观察时间、观察次数和对应的 `segment_id`。候选可保持现有低延迟字幕体验，但不能直接走现有 `publish_final`。

候选阶段允许：

- 继续显示 ASR partial 和本机 Apple 草稿；
- 维持最新版本覆盖，不能排队积压。

候选阶段禁止：

- 写入永久文稿；
- 触发 Smart Hint；
- 触发远程 Final 或将远程翻译标记为已定稿。

### 2. 候选 seal 规则

初始实验值为：候选 prefix 在 **两次不同 stable observation** 中一致，且距首次候选至少 **350 ms**，才可 seal 成既有的 `ASRSemanticFinal`。真正的 native source-final 包含该 prefix 时可立即 seal。

`350 ms`、观察次数及现有 `host_min_words` / `host_force_words` 都是实验参数，不在 Phase 1 直接暴露给 Dashboard；先通过回放与实机数据决定是否保留。

### 3. Native source-final 是权威文本

source-final 到来时，Coordinator 必须按规范化 token 对齐已 seal 与待 seal 段：

| 场景 | 必须行为 |
| --- | --- |
| prefix 相同 | seal 候选，保留 segment ID，不重复发请求。 |
| 候选 prefix 被改写 | 以相同 segment ID 替换候选，再等待新的稳定规则；不得留下旧词。 |
| 已 seal prefix 被改写 | 发出同 ID、递增 revision 的 source correction；显示、远程终稿与文稿必须由更新版本覆盖。 |
| source-final 仅补充 remainder | 原有段不重发；只处理新的 remainder。 |

已 seal 的修订是本计划最难部分。实现可以新增明确的 correction event，或扩展现有 coordinator callback；无论采用哪种形态，必须保留 `segment_id`、严格递增 revision，并遵守 `latest-wins`，不能让旧远程回答覆盖纠正后的文本。

## 分阶段实施

### Phase 0 — 先补事实与回归安全网（已完成）

不改运行代码。新增纯 Coordinator trace fixtures：

1. 稳定带句号 partial 后，source-final 改写早期词（例如 `figure → model`）。
2. Parakeet host discourse boundary 后，后续 partial 改写候选 prefix。
3. prefix 未改写、source-final 只增加尾部。
4. pause/reset 后旧 stream 的 correction 不能进入新 stream。
5. 同一 source revision 的重复事件不重复翻译、不重复写文稿。

验收：当前缺陷必须先红，再用未来实现转绿；Apple 与 MLX 的既有 coordinator contract 保持绿。

### Phase 1 — 候选段与 seal（已完成）

在 `ASRSubtitleCoordinator` / `IncrementalSegmenter` 增加候选状态，只对 `host_semantic_boundaries=True` 生效。把 host cut 与 native `source_final=True` 的语义区分开；Apple 与 MLX 不进入新分支。

验收：

- Parakeet 仍在首次 partial 后立即显示本机草稿；
- host candidate 未 seal 前不触发 Final、Smart Hint、永久记录；
- 连续两个 stable observation 后只生成一次 semantic final；
- `source_final` 立即清空/封存正确的候选状态，pause/reset 不泄漏。

### Phase 2 — 已 seal 段的 source-final correction（已完成，限同段词替换）

为 source correction 建立同 ID revision 语义，并接入 `SegmentStore`、显示事件、远程 Final latest-wins 和文稿覆盖策略。先处理一段内的 token 替换；跨段重新切分仅在有可复现 trace 后单独设计，不和本阶段混合。

验收：

- final 修订后的英文、中文终稿和文稿一致；
- 旧 Final 网络回答不能覆盖更新 revision；
- 不产生第二条 semantic segment 或重复 Smart Hint；
- 停止、暂停、恢复和过期 worker 的 acceptance gate 合同不变。

### Phase 3 — EOU 参数实验，不与正确性改动混合

使用同一段已获许可、未提交到仓库的系统音频，分别跑 `eouDebounceMs = 320 / 480 / 640 / 800`。保持 50 ms 输入 cadence、160 ms Parakeet 内部 chunk、模型和 compute setting 不变。

记录每组：首 token、首 ≥3 词、EOU 数、候选/正式段数、跨句合并、人工复核的错误切分、CPU 平均/峰值、RSS 峰值。只有 Phase 1/2 通过后才允许选择新 debounce；不得仅因 EOU 数更多就下调阈值。

### Phase 4 — 真实课堂验收与产品决策

每组至少包含连续 60–120 秒系统音频与自然 pause/resume。使用 Diagnostics，人工查看：英文修订、中文覆盖、文稿、全屏玻璃/刘海、远程 provider timeout 下的行为。

满足以下条件前，Parakeet 保持实验状态：

- 首 ≥3 词延迟不比当前 1.33 s 基线退化超过 150 ms；
- 所有注入的 native source-final 修订最终可见且可记录；
- 没有 stale 翻译回写、段 ID 倒退、重复文稿或跨 pause 粘连；
- CPU/RSS 不高于当前基线的 10%，除非有明确、人工验证的课堂收益；
- Apple 的同一验证不出现行为或延迟回归。

## 实施顺序与回滚

每个 Phase 单独提交、独立测试。出现以下任一情况立即回滚到上一个阶段：Apple 首字幕延迟增加、远程 Final 被候选阻塞、source correction 生成重复记录、或 native helper reset 后旧事件可见。

不要采取以下“快捷修复”：降低 `host_force_words`、增加固定 timer 强制分句、把每个 partial 当 final、用远程模型判断英文句界、或复制 Apple source-final 行为。它们会掩盖而非解决 Parakeet 的 EOU 与修订语义差异。
