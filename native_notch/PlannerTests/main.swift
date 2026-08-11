import CoreGraphics

private func check(_ condition: @autoclosure () -> Bool, _ message: String) {
    guard condition() else {
        fatalError(message)
    }
}

let runs = SubtitlePresentationPlanner.revisionRuns(
    from: "这个人很喜欢吃西瓜。",
    to: "小花狗很喜欢吃草莓。"
)
check(runs.map(\.text).joined() == "小花狗很喜欢吃草莓。", "revision text")
check(
    runs.filter { !$0.changed }.map(\.text).joined().contains("很喜欢吃"),
    "stable middle run"
)
check(
    runs.filter(\.changed).map(\.text).joined().contains("草莓"),
    "changed suffix"
)
check(
    SubtitlePresentationPlanner.revisionRuns(from: "", to: "第一次翻译")
        == [RevisionRun(text: "第一次翻译", changed: false)],
    "first frame must not highlight"
)
check(SubtitlePresentationPlanner.quantizedWidth(for: 0) == 360, "minimum width")
check(SubtitlePresentationPlanner.quantizedWidth(for: 300) == 392, "width bucket")
check(SubtitlePresentationPlanner.quantizedWidth(for: 1000) == 560, "maximum width")
check(
    SubtitlePresentationPlanner.resizeIntent(
        currentWidth: 392,
        targetWidth: 424
    ) == .growImmediately,
    "growth policy"
)
check(
    SubtitlePresentationPlanner.resizeIntent(
        currentWidth: 424,
        targetWidth: 392
    ) == .shrinkAfterDelay,
    "shrink policy"
)
check(
    SubtitlePresentationPlanner.resizeIntent(
        currentWidth: 424,
        targetWidth: 392,
        force: true
    ) == .replaceImmediately,
    "forced resize policy"
)
check(
    SubtitlePresentationPlanner.estimatedLineCount(
        measuredTextWidth: 300,
        availableWidth: 400
    ) == 1,
    "single-line estimate"
)
check(
    SubtitlePresentationPlanner.estimatedLineCount(
        measuredTextWidth: 500,
        availableWidth: 400
    ) == 2,
    "two-line estimate"
)
check(
    SubtitlePresentationPlanner.lineReservationIntent(
        required: 2,
        reserved: 3,
        pendingShrinkTarget: nil
    ) == .scheduleShrink,
    "first 3-to-2 revision schedules a shrink"
)
check(
    SubtitlePresentationPlanner.lineReservationIntent(
        required: 2,
        reserved: 3,
        pendingShrinkTarget: 2
    ) == .keepPendingShrink,
    "same 3-to-2 target keeps the existing cooldown"
)
check(
    SubtitlePresentationPlanner.lineReservationIntent(
        required: 3,
        reserved: 3,
        pendingShrinkTarget: 2
    ) == .replaceImmediately,
    "line growth cancels a pending shrink"
)

func cue(
    _ id: Int,
    translated: String = "译文",
    fragments: [NotchFragment]? = nil
) -> NotchCue {
    NotchCue(
        id: id,
        segmentID: id,
        original: "source \(id)",
        translated: translated,
        finalized: false,
        committedPrefixLength: 0,
        fragments: fragments
    )
}

let initialPresentation = NotchRollupPlanner.reconcile(
    current: NotchPresentationState(),
    incoming: [cue(1), cue(2, translated: "草稿")]
)
let sameSegmentRevision = NotchRollupPlanner.reconcile(
    current: initialPresentation,
    incoming: [cue(1), cue(2, translated: "最终译文")]
)
check(
    sameSegmentRevision.history.map(\.semanticID) == [1],
    "same-segment revision preserves history"
)
check(
    sameSegmentRevision.active?.translated == "最终译文",
    "same-segment revision updates active"
)
check(
    sameSegmentRevision.rollupGeneration
        == initialPresentation.rollupGeneration,
    "same-segment revision does not roll up"
)
check(
    sameSegmentRevision.visibleCues(displayCount: 1).map(\.semanticID) == [2],
    "small mode shows active only"
)
check(
    sameSegmentRevision.visibleCues(displayCount: 2).map(\.semanticID) == [1, 2],
    "medium mode shows one history cue and active"
)
let mediumSlots = sameSegmentRevision.visibleSlots(displayCount: 2)
check(mediumSlots.map(\.id) == [1, 2], "slot identity follows semantic cue")
check(mediumSlots[0].role == .history(index: 0), "history slot role")
check(mediumSlots[1].role == .active, "active slot role")

let newSegment = NotchRollupPlanner.reconcile(
    current: sameSegmentRevision,
    incoming: [cue(1), cue(2), cue(3)]
)
check(newSegment.history.map(\.semanticID) == [1, 2], "bounded history")
check(newSegment.active?.semanticID == 3, "new active segment")
check(
    newSegment.rollupGeneration
        == sameSegmentRevision.rollupGeneration + 1,
    "new segment rolls up once"
)
let lateHistoryRevision = NotchRollupPlanner.reconcile(
    current: newSegment,
    incoming: [cue(1), cue(2, translated: "迟到最终稿"), cue(3)]
)
check(
    lateHistoryRevision.history.map(\.semanticID) == [1, 2],
    "late history revision does not reorder"
)
check(
    lateHistoryRevision.history.last?.translated == "迟到最终稿",
    "late history revision updates in place"
)
check(
    lateHistoryRevision.rollupGeneration == newSegment.rollupGeneration,
    "late history revision does not roll up"
)

let fragments = [
    NotchFragment(
        id: 7000,
        original: "first",
        translated: "第一部分",
        finalized: true,
        committedPrefixLength: 4
    ),
    NotchFragment(
        id: 7001,
        original: "second",
        translated: "第二部分",
        finalized: true,
        committedPrefixLength: 4
    ),
]
let fragmented = NotchRollupPlanner.reconcile(
    current: NotchPresentationState(),
    incoming: [cue(7, fragments: fragments)]
)
check(fragmented.allCues.count == 1, "fragments stay in one cue")
check(fragmented.active?.displayFragments.count == 2, "fragments remain visible")
check(
    fragmented.active?.latestDisplayFragment.id == 7001,
    "one notch slot paints only the newest fragment"
)

let expiredShort = NotchRollupPlanner.reconcile(
    current: initialPresentation,
    incoming: [cue(1)]
)
check(expiredShort.active?.semanticID == 1, "short expiry reveals prior cue")
check(
    expiredShort.rollupGeneration == initialPresentation.rollupGeneration,
    "short expiry does not roll up"
)

print("SubtitlePresentationPlanner tests passed")
