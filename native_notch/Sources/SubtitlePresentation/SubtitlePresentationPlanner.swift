import CoreGraphics

/// One visual run in an incremental subtitle revision. Equal runs retain their
/// identity and styling; only inserted or replaced runs are emphasized.
public struct RevisionRun: Equatable {
    public let text: String
    public let changed: Bool

    public init(text: String, changed: Bool) {
        self.text = text
        self.changed = changed
    }
}

public enum SubtitleResizeIntent: Equatable {
    case unchanged
    case growImmediately
    case shrinkAfterDelay
    case replaceImmediately
}

public enum LineReservationIntent: Equatable {
    case replaceImmediately
    case keepPendingShrink
    case scheduleShrink
}

/// Pure display policy for incremental subtitle revisions. It deliberately has
/// no SwiftUI, networking, ASR, or model dependencies, so presentation tuning
/// cannot delay the realtime translation path.
public enum SubtitlePresentationPlanner {
    public static let minimumWidth: CGFloat = 360
    public static let maximumWidth: CGFloat = 560
    public static let widthStep: CGFloat = 32
    public static let reservedEdgeWidth: CGFloat = 80
    public static let finalLayoutHoldSeconds = 0.40
    public static let shrinkDelaySeconds = 0.65
    public static let shrinkAnimationSeconds = 0.20
    public static let lineShrinkDelaySeconds = 0.80
    public static let translatedLineHeight: CGFloat = 20

    public static func revisionRuns(
        from oldText: String,
        to newText: String
    ) -> [RevisionRun] {
        guard oldText != newText else {
            return newText.isEmpty ? [] : [RevisionRun(text: newText, changed: false)]
        }
        guard !oldText.isEmpty else {
            // Initial content is not a correction and should not flash.
            return newText.isEmpty ? [] : [RevisionRun(text: newText, changed: false)]
        }

        let old = Array(oldText)
        let new = Array(newText)
        let columns = new.count + 1
        var lcs = Array(repeating: 0, count: (old.count + 1) * columns)
        if !old.isEmpty && !new.isEmpty {
            for left in stride(from: old.count - 1, through: 0, by: -1) {
                for right in stride(from: new.count - 1, through: 0, by: -1) {
                    let index = left * columns + right
                    if old[left] == new[right] {
                        lcs[index] = 1 + lcs[(left + 1) * columns + right + 1]
                    } else {
                        lcs[index] = max(
                            lcs[(left + 1) * columns + right],
                            lcs[left * columns + right + 1]
                        )
                    }
                }
            }
        }

        var runs: [RevisionRun] = []
        func append(_ character: Character, changed: Bool) {
            if let last = runs.last, last.changed == changed {
                runs[runs.count - 1] = RevisionRun(
                    text: last.text + String(character),
                    changed: changed
                )
            } else {
                runs.append(RevisionRun(text: String(character), changed: changed))
            }
        }

        var left = 0
        var right = 0
        while left < old.count && right < new.count {
            if old[left] == new[right] {
                append(new[right], changed: false)
                left += 1
                right += 1
            } else if lcs[(left + 1) * columns + right]
                        >= lcs[left * columns + right + 1] {
                left += 1
            } else {
                append(new[right], changed: true)
                right += 1
            }
        }
        while right < new.count {
            append(new[right], changed: true)
            right += 1
        }
        return runs
    }

    public static func quantizedWidth(for measuredTextWidth: CGFloat) -> CGFloat {
        let desired = max(minimumWidth, measuredTextWidth + reservedEdgeWidth)
        let steps = ceil(max(0, desired - minimumWidth) / widthStep)
        return min(maximumWidth, minimumWidth + steps * widthStep)
    }

    public static func resizeIntent(
        currentWidth: CGFloat,
        targetWidth: CGFloat,
        force: Bool = false
    ) -> SubtitleResizeIntent {
        guard targetWidth != currentWidth else { return .unchanged }
        if force { return .replaceImmediately }
        return targetWidth > currentWidth ? .growImmediately : .shrinkAfterDelay
    }

    public static func estimatedLineCount(
        measuredTextWidth: CGFloat,
        availableWidth: CGFloat,
        maximumLines: Int = 2
    ) -> Int {
        guard measuredTextWidth > 0 else { return 1 }
        let safeWidth = max(1, availableWidth)
        return min(maximumLines, max(1, Int(ceil(measuredTextWidth / safeWidth))))
    }

    public static func lineReservationIntent(
        required: Int,
        reserved: Int,
        pendingShrinkTarget: Int?,
        force: Bool = false
    ) -> LineReservationIntent {
        if required >= reserved || force {
            return .replaceImmediately
        }
        if pendingShrinkTarget == required {
            return .keepPendingShrink
        }
        return .scheduleShrink
    }
}
