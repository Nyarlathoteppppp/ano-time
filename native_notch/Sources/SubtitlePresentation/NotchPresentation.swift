/// A visual fragment belongs to one semantic cue. Splitting a long sentence
/// must never create another history entry.
public struct NotchFragment: Codable, Identifiable, Equatable {
    public let id: Int
    public let original: String
    public let translated: String
    public let finalized: Bool?
    public let committedPrefixLength: Int?

    public init(
        id: Int,
        original: String,
        translated: String,
        finalized: Bool?,
        committedPrefixLength: Int?
    ) {
        self.id = id
        self.original = original
        self.translated = translated
        self.finalized = finalized
        self.committedPrefixLength = committedPrefixLength
    }
}

/// One ASR segment and all of its display-only fragments.
public struct NotchCue: Codable, Identifiable, Equatable {
    public let id: Int
    public let segmentID: Int?
    public let original: String
    public let translated: String
    public let finalized: Bool?
    public let committedPrefixLength: Int?
    public let fragments: [NotchFragment]?

    public var semanticID: Int { segmentID ?? id }

    public init(
        id: Int,
        segmentID: Int? = nil,
        original: String,
        translated: String,
        finalized: Bool?,
        committedPrefixLength: Int?,
        fragments: [NotchFragment]?
    ) {
        self.id = id
        self.segmentID = segmentID
        self.original = original
        self.translated = translated
        self.finalized = finalized
        self.committedPrefixLength = committedPrefixLength
        self.fragments = fragments
    }

    public var displayFragments: [NotchFragment] {
        if let fragments, !fragments.isEmpty { return fragments }
        return [NotchFragment(
            id: id * 1000,
            original: original,
            translated: translated,
            finalized: finalized,
            committedPrefixLength: committedPrefixLength
        )]
    }

    /// Compatibility accessor for compact history rendering. Active cues use
    /// ``displayWindow(for:)`` so a long translation retains recent context.
    public var latestDisplayFragment: NotchFragment {
        displayFragments.last!
    }
}

/// A bounded, ordered projection of one semantic cue. It is presentation-only:
/// every fragment continues to belong to its parent ``NotchCue.semanticID``.
public struct NotchFragmentWindow: Equatable {
    public let fragments: [NotchFragment]
    public let hasHiddenPrefix: Bool

    public init(fragments: [NotchFragment], hasHiddenPrefix: Bool) {
        self.fragments = fragments
        self.hasHiddenPrefix = hasHiddenPrefix
    }
}

/// Stable roll-up state. Text revisions replace `active` in place; history is
/// advanced only when a genuinely newer semantic segment arrives.
public struct NotchPresentationState: Equatable {
    public var history: [NotchCue]
    public var active: NotchCue?
    public var rollupGeneration: Int

    public init(
        history: [NotchCue] = [],
        active: NotchCue? = nil,
        rollupGeneration: Int = 0
    ) {
        self.history = history
        self.active = active
        self.rollupGeneration = rollupGeneration
    }

    public var allCues: [NotchCue] {
        history + (active.map { [$0] } ?? [])
    }

    public func visibleCues(displayCount: Int) -> [NotchCue] {
        let count = max(1, min(3, displayCount))
        return Array(allCues.suffix(count))
    }

    public func visibleSlots(displayCount: Int) -> [NotchCueSlot] {
        let cues = visibleCues(displayCount: displayCount)
        return cues.enumerated().map { index, cue in
            NotchCueSlot(
                cue: cue,
                role: index == cues.count - 1
                    ? .active
                    : .history(index: index)
            )
        }
    }
}

public enum NotchCueRole: Equatable {
    case history(index: Int)
    case active
}

public extension NotchCue {
    /// Keep current speech readable without allowing one long cue to consume
    /// the entire DynamicNotch. History remains compact; the active cue keeps
    /// two ordered fragments and explicitly signals omitted earlier context.
    func displayWindow(for role: NotchCueRole) -> NotchFragmentWindow {
        let allFragments = displayFragments
        guard case .active = role else {
            return NotchFragmentWindow(
                fragments: [allFragments.last!],
                hasHiddenPrefix: false
            )
        }
        let activeFragmentLimit = 2
        let start = max(0, allFragments.count - activeFragmentLimit)
        return NotchFragmentWindow(
            fragments: Array(allFragments[start...]),
            hasHiddenPrefix: start > 0
        )
    }
}

/// A stable semantic cue plus its current presentation role. Identity follows
/// the cue, not the slot, so SwiftUI can move an existing cue instead of
/// destroying it when it rolls from active into history.
public struct NotchCueSlot: Identifiable, Equatable {
    public let cue: NotchCue
    public let role: NotchCueRole

    public var id: Int { cue.semanticID }

    public init(cue: NotchCue, role: NotchCueRole) {
        self.cue = cue
        self.role = role
    }
}

/// Monotonic ordering for frames received from the Python native-notch bridge.
/// A helper restart creates a new generation; within that generation only a
/// strictly newer frame may change the rendered state.  The type deliberately
/// lives in this framework so the transport rule can be tested without AppKit.
public struct NotchFrameOrder: Equatable {
    public private(set) var generation: Int?
    public private(set) var frameID: Int?

    public init() {}

    /// Accept a legacy frame with no transport metadata for compatibility.
    /// Metadata-bearing frames must be newer than the last accepted frame.
    public mutating func accepts(generation: Int?, frameID: Int?) -> Bool {
        guard let generation, let frameID else { return true }

        guard let acceptedGeneration = self.generation else {
            self.generation = generation
            self.frameID = frameID
            return true
        }
        if generation < acceptedGeneration {
            return false
        }
        if generation > acceptedGeneration {
            self.generation = generation
            self.frameID = frameID
            return true
        }
        guard let acceptedFrameID = self.frameID else {
            self.frameID = frameID
            return true
        }
        guard frameID > acceptedFrameID else { return false }
        self.frameID = frameID
        return true
    }
}

public enum NotchRollupPlanner {
    public static let maximumHistoryCount = 2

    public static func reconcile(
        current: NotchPresentationState,
        incoming: [NotchCue]
    ) -> NotchPresentationState {
        guard let incomingActive = incoming.last else {
            return NotchPresentationState(
                rollupGeneration: current.rollupGeneration
            )
        }

        guard let currentActive = current.active else {
            return NotchPresentationState(
                history: Array(incoming.dropLast().suffix(maximumHistoryCount)),
                active: incomingActive,
                rollupGeneration: current.rollupGeneration
            )
        }

        if incomingActive.semanticID == currentActive.semanticID {
            var revisions: [Int: NotchCue] = [:]
            for cue in incoming {
                revisions[cue.semanticID] = cue
            }
            return NotchPresentationState(
                history: current.history.map {
                    revisions[$0.semanticID] ?? $0
                },
                active: incomingActive,
                rollupGeneration: current.rollupGeneration
            )
        }

        // A hidden/expired short fragment can reveal an older cue again. That
        // is a projection correction, not a new sentence and must not roll up.
        guard incomingActive.semanticID > currentActive.semanticID else {
            return NotchPresentationState(
                history: Array(incoming.dropLast().suffix(maximumHistoryCount)),
                active: incomingActive,
                rollupGeneration: current.rollupGeneration
            )
        }

        return NotchPresentationState(
            history: Array(incoming.dropLast().suffix(maximumHistoryCount)),
            active: incomingActive,
            rollupGeneration: current.rollupGeneration + 1
        )
    }
}
