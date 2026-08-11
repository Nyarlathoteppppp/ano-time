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

print("SubtitlePresentationPlanner tests passed")
