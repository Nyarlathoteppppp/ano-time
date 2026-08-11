import AppKit
import DynamicNotchKit
import SubtitlePresentation
import SwiftUI

@MainActor
private enum MascotAsset {
    static let image: NSImage? = {
        let sourceFile = URL(fileURLWithPath: #filePath)
        let imageURL = sourceFile
            .deletingLastPathComponent()
            .appendingPathComponent("Resources/ano-smile@2x.png")
        guard let image = NSImage(contentsOf: imageURL) else { return nil }
        image.size = NSSize(width: 26, height: 26)
        return image
    }()
}

@MainActor
private enum TrailingMascotAsset {
    static let image: NSImage? = {
        let sourceFile = URL(fileURLWithPath: #filePath)
        let imageURL = sourceFile
            .deletingLastPathComponent()
            .appendingPathComponent("Resources/lgcr@2x.png")
        guard let image = NSImage(contentsOf: imageURL) else { return nil }
        image.size = NSSize(width: 26, height: 26)
        return image
    }()
}

private struct InputMessage: Decodable {
    let command: String?
    let original: String?
    let translated: String?
    let items: [SubtitleLine]?
    let paused: Bool?
    let busyStages: [String]?
}

private struct SubtitleFragment: Codable, Identifiable {
    let id: Int
    let original: String
    let translated: String
    let finalized: Bool?
    let committedPrefixLength: Int?
}

private struct SubtitleLine: Codable, Identifiable {
    let id: Int
    let original: String
    let translated: String
    let finalized: Bool?
    let committedPrefixLength: Int?
    let fragments: [SubtitleFragment]?
}

@MainActor
private final class SubtitleState: ObservableObject {
    private static let sizeDefaults = UserDefaults(
        suiteName: "com.nyarlathotep.realtime-ton.notch"
    )

    @Published var items = [
        SubtitleLine(
            id: 0,
            original: "Waiting for speech…",
            translated: "",
            finalized: false,
            committedPrefixLength: 0,
            fragments: nil
        )
    ] {
        didSet {
            refreshContentWidth()
            refreshTranslationLineReservation()
        }
    }
    @Published var displayCount: Int
    @Published private(set) var contentWidth: CGFloat = 360
    @Published private(set) var reservedTranslationLineCount = 1
    @Published var isPaused = false
    var compactTask: Task<Void, Never>?
    private(set) var subtitleGeneration = 0
    private(set) var activityGeneration = 0
    private var busyStages = Set<String>()
    private var widthShrinkTask: Task<Void, Never>?
    private var translationLineShrinkTask: Task<Void, Never>?
    private var pendingTranslationLineTarget: Int?
    private var finalLayoutTask: Task<Void, Never>?
    private var holdsFinalLayout = false
    private var modeTransitionTask: Task<Void, Never>?
    private var isChangingDisplayCount = false
    var onExpand: (() -> Void)?
    var onCycleSize: (() -> Void)?
    var onPause: (() -> Void)?
    var onGlass: (() -> Void)?
    var onExit: (() -> Void)?

    init() {
        let saved = Self.sizeDefaults?.integer(forKey: "displayCount") ?? 0
        displayCount = (1...3).contains(saved) ? saved : 2
    }

    func replaceItems(_ newItems: [SubtitleLine]) {
        subtitleGeneration += 1
        let authoritativeFinalRevision = hasSameItemIdentity(as: newItems)
            && zip(items, newItems).contains { oldItem, newItem in
                oldItem.translated != newItem.translated
                    && newItem.finalized == true
                    && isFullyCommitted(newItem)
            }
        if authoritativeFinalRevision {
            finalLayoutTask?.cancel()
            holdsFinalLayout = true
        }
        items = newItems
        if authoritativeFinalRevision {
            finalLayoutTask = Task { @MainActor [weak self] in
                try? await Task.sleep(
                    for: .seconds(SubtitlePresentationPlanner.finalLayoutHoldSeconds)
                )
                guard let self, !Task.isCancelled else { return }
                self.holdsFinalLayout = false
                self.refreshContentWidth(animated: true)
            }
        }
    }

    private func isFullyCommitted(_ item: SubtitleLine) -> Bool {
        if let fragments = item.fragments, !fragments.isEmpty {
            return fragments.allSatisfy { fragment in
                (fragment.committedPrefixLength ?? 0) >= fragment.translated.count
            }
        }
        return (item.committedPrefixLength ?? 0) >= item.translated.count
    }

    func hasSameItemIdentity(as newItems: [SubtitleLine]) -> Bool {
        items.map(\.id) == newItems.map(\.id)
    }

    func visibleRows() -> [SubtitleFragment] {
        let rows = items.flatMap { item -> [SubtitleFragment] in
            if let fragments = item.fragments, !fragments.isEmpty {
                return fragments
            }
            return [SubtitleFragment(
                id: item.id * 1000,
                original: item.original,
                translated: item.translated,
                finalized: item.finalized,
                committedPrefixLength: item.committedPrefixLength
            )]
        }
        return Array(rows.suffix(displayCount))
    }

    func replaceBusyStages(_ stages: [String]) {
        let replacement = Set(stages)
        guard replacement != busyStages else { return }
        busyStages = replacement
        activityGeneration += 1
    }

    func clearActivity() {
        guard !busyStages.isEmpty else { return }
        busyStages.removeAll()
        activityGeneration += 1
    }

    var hasActiveWork: Bool { !busyStages.isEmpty }

    var hasSubtitleContent: Bool {
        !items.isEmpty && !(items.count == 1
            && items[0].id == 0
            && items[0].original == "Waiting for speech…")
    }

    func cycleSize() {
        modeTransitionTask?.cancel()
        widthShrinkTask?.cancel()
        isChangingDisplayCount = true
        let nextDisplayCount = displayCount == 3 ? 1 : displayCount + 1
        if nextDisplayCount < displayCount {
            withAnimation(.easeInOut(duration: 0.45)) {
                displayCount = nextDisplayCount
            }
        } else {
            displayCount = nextDisplayCount
        }
        Self.sizeDefaults?.set(displayCount, forKey: "displayCount")
        modeTransitionTask = Task { @MainActor [weak self] in
            try? await Task.sleep(for: .seconds(0.30))
            guard let self, !Task.isCancelled else { return }
            self.isChangingDisplayCount = false
            self.refreshContentWidth(
                allowImmediateShrink: true,
                animated: true
            )
            self.refreshTranslationLineReservation(allowImmediateShrink: true)
        }
    }

    private func measuredContentWidth() -> CGFloat {
        let visibleItems = visibleRows()
        let englishFont = NSFont.systemFont(ofSize: 11.5, weight: .regular)
        let translatedFont = NSFont.systemFont(ofSize: 16, weight: .semibold)
        let measured = visibleItems.reduce(CGFloat(0)) { longest, item in
            let hidesOriginal = (
                displayCount == 1 && !item.translated.isEmpty
            ) || (
                displayCount == 3
                    && item.id == visibleItems.first?.id
                    && !item.translated.isEmpty
            )
            let englishWidth = hidesOriginal ? 0 : (item.original as NSString).size(
                withAttributes: [.font: englishFont]
            ).width
            let translatedWidth = (item.translated as NSString).size(
                withAttributes: [.font: translatedFont]
            ).width
            return max(longest, max(englishWidth, translatedWidth))
        }
        // Reserve equal space for the two edge mascots so subtitles remain
        // centered and never run underneath either image.
        return SubtitlePresentationPlanner.quantizedWidth(for: measured)
    }

    private func setContentWidth(_ width: CGFloat, animated: Bool) {
        guard width != contentWidth else { return }
        let isShrinking = width < contentWidth
        if animated && isShrinking {
            withAnimation(.easeInOut(
                duration: SubtitlePresentationPlanner.shrinkAnimationSeconds
            )) {
                contentWidth = width
            }
        } else {
            contentWidth = width
        }
        refreshTranslationLineReservation()
    }

    private func measuredTranslationLineCount() -> Int {
        let availableWidth = max(
            1,
            contentWidth - SubtitlePresentationPlanner.reservedEdgeWidth
        )
        let translatedFont = NSFont.systemFont(ofSize: 16, weight: .semibold)
        return visibleRows().reduce(0) { total, row in
            guard !row.translated.isEmpty else { return total }
            let measured = (row.translated as NSString).size(
                withAttributes: [.font: translatedFont]
            ).width
            return total + SubtitlePresentationPlanner.estimatedLineCount(
                measuredTextWidth: measured,
                availableWidth: availableWidth
            )
        }
    }

    var translationBottomReserve: CGFloat {
        let currentLines = measuredTranslationLineCount()
        return CGFloat(max(0, reservedTranslationLineCount - currentLines))
            * SubtitlePresentationPlanner.translatedLineHeight
    }

    private func refreshTranslationLineReservation(
        allowImmediateShrink: Bool = false
    ) {
        let required = measuredTranslationLineCount()
        let intent = SubtitlePresentationPlanner.lineReservationIntent(
            required: required,
            reserved: reservedTranslationLineCount,
            pendingShrinkTarget: pendingTranslationLineTarget,
            force: allowImmediateShrink
        )
        if intent == .replaceImmediately || required == 0 {
            translationLineShrinkTask?.cancel()
            translationLineShrinkTask = nil
            pendingTranslationLineTarget = nil
            var immediate = Transaction()
            immediate.disablesAnimations = true
            withTransaction(immediate) {
                reservedTranslationLineCount = required
            }
            return
        }
        if intent == .keepPendingShrink {
            // Repeated partial/preview revisions with the same two-line target
            // must not restart the cooldown forever.
            return
        }
        translationLineShrinkTask?.cancel()
        pendingTranslationLineTarget = required
        translationLineShrinkTask = Task { @MainActor [weak self] in
            try? await Task.sleep(
                for: .seconds(SubtitlePresentationPlanner.lineShrinkDelaySeconds)
            )
            guard let self, !Task.isCancelled else { return }
            let latestRequired = self.measuredTranslationLineCount()
            guard latestRequired < self.reservedTranslationLineCount else {
                self.pendingTranslationLineTarget = nil
                self.translationLineShrinkTask = nil
                return
            }
            withAnimation(.easeInOut(
                duration: SubtitlePresentationPlanner.shrinkAnimationSeconds
            )) {
                self.reservedTranslationLineCount = latestRequired
            }
            self.pendingTranslationLineTarget = nil
            self.translationLineShrinkTask = nil
        }
    }

    private func refreshContentWidth(
        allowImmediateShrink: Bool = false,
        animated: Bool = true
    ) {
        if isChangingDisplayCount && !allowImmediateShrink {
            return
        }
        let targetWidth = measuredContentWidth()
        // A final correction may grow beyond the current frame. Let growth
        // through immediately to avoid clipping, while holding only shrinkage
        // until the short final-layout stabilization window expires.
        if holdsFinalLayout
            && targetWidth <= contentWidth
            && !allowImmediateShrink {
            return
        }
        widthShrinkTask?.cancel()

        let resizeIntent = SubtitlePresentationPlanner.resizeIntent(
            currentWidth: contentWidth,
            targetWidth: targetWidth,
            force: allowImmediateShrink
        )
        if resizeIntent == .unchanged {
            return
        }
        if resizeIntent == .growImmediately || resizeIntent == .replaceImmediately {
            setContentWidth(
                targetWidth,
                animated: animated && resizeIntent == .replaceImmediately
            )
            return
        }

        // Growing text must never be clipped. Shrinking is intentionally
        // delayed so partial-ASR corrections do not make the notch breathe.
        widthShrinkTask = Task { @MainActor [weak self] in
            try? await Task.sleep(
                for: .seconds(SubtitlePresentationPlanner.shrinkDelaySeconds)
            )
            guard let self, !Task.isCancelled else { return }
            let latestTarget = self.measuredContentWidth()
            if latestTarget < self.contentWidth {
                self.setContentWidth(latestTarget, animated: true)
            }
        }
    }

}

private func emitEvent(_ event: String) {
    let payload = ["event": event]
    guard let data = try? JSONSerialization.data(withJSONObject: payload),
          var line = String(data: data, encoding: .utf8) else { return }
    line.append("\n")
    FileHandle.standardOutput.write(Data(line.utf8))
}

private struct StableStreamingText: View {
    let text: String
    let committedPrefixLength: Int

    @State private var displayedText: String
    @State private var displayedRuns: [RevisionRun]
    @State private var clearHighlightTask: Task<Void, Never>?

    init(text: String, committedPrefixLength: Int) {
        self.text = text
        self.committedPrefixLength = committedPrefixLength
        _displayedText = State(initialValue: text)
        _displayedRuns = State(initialValue:
            SubtitlePresentationPlanner.revisionRuns(from: "", to: text)
        )
    }

    private var styledText: Text {
        guard !displayedText.isEmpty else { return Text("…") }
        let stableBoundary = max(0, min(committedPrefixLength, displayedText.count))
        var offset = 0
        var result = Text("")
        for run in displayedRuns {
            let runCount = run.text.count
            let stableCount = max(0, min(runCount, stableBoundary - offset))
            if stableCount > 0 {
                result = result + Text(String(run.text.prefix(stableCount)))
                    .foregroundColor(.white)
            }
            let mutable = String(run.text.dropFirst(stableCount))
            if !mutable.isEmpty {
                if run.changed {
                    result = result + Text(mutable)
                        .foregroundColor(.white)
                        .bold()
                } else {
                    result = result + Text(mutable)
                        .foregroundColor(.white.opacity(0.82))
                }
            }
            offset += runCount
        }
        return result
    }

    private func replaceText(with newText: String) {
        guard newText != displayedText else { return }
        let oldText = displayedText
        let nextRuns = SubtitlePresentationPlanner.revisionRuns(
            from: oldText,
            to: newText
        )

        var immediate = Transaction()
        immediate.disablesAnimations = true
        withTransaction(immediate) {
            displayedText = newText
            displayedRuns = nextRuns
        }
        clearHighlightTask?.cancel()
        clearHighlightTask = Task { @MainActor in
            try? await Task.sleep(nanoseconds: 180_000_000)
            guard !Task.isCancelled, displayedText == newText else { return }
            var transaction = Transaction()
            transaction.disablesAnimations = true
            withTransaction(transaction) {
                displayedRuns = newText.isEmpty
                    ? []
                    : [RevisionRun(text: newText, changed: false)]
            }
        }
    }

    var body: some View {
        ZStack {
            styledText
                .font(.system(size: 16, weight: .semibold))
                .lineLimit(2)
                .multilineTextAlignment(.center)
                .frame(maxWidth: .infinity, alignment: .center)
                .contentTransition(.identity)
                .transaction { transaction in
                    transaction.animation = nil
                    transaction.disablesAnimations = true
                }
        }
            .onChange(of: text, perform: replaceText)
            .onDisappear {
                clearHighlightTask?.cancel()
            }
    }
}

private struct SubtitleContent: View {
    @ObservedObject var state: SubtitleState

    var body: some View {
        let visibleItems = state.visibleRows()
        ZStack(alignment: .top) {
            VStack(alignment: .center, spacing: 5) {
                ForEach(visibleItems) { item in
                    VStack(alignment: .center, spacing: 2) {
                        let hidesOriginal = (
                            state.displayCount == 1 && !item.translated.isEmpty
                        ) || (
                            state.displayCount == 3
                                && item.id == visibleItems.first?.id
                                && !item.translated.isEmpty
                        )
                        if !hidesOriginal {
                            Text(item.original)
                                .font(.system(
                                    size: 11.5,
                                    weight: item.finalized == true ? .medium : .regular
                                ))
                                .foregroundStyle(
                                    .white.opacity(item.finalized == true ? 0.96 : 0.78)
                                )
                                .lineLimit(1)
                                .multilineTextAlignment(.center)
                                .frame(maxWidth: .infinity, alignment: .center)
                        }

                        if !item.translated.isEmpty {
                            StableStreamingText(
                                text: item.translated,
                                committedPrefixLength: item.committedPrefixLength ?? 0
                            )
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .center)
                }
            }
            .padding(.horizontal, 40)
            .padding(.bottom, state.translationBottomReserve)

            HStack(spacing: 0) {
                if let mascotImage = MascotAsset.image {
                    Image(nsImage: mascotImage)
                        .frame(width: 26, height: 26)
                }
                Spacer(minLength: 0)
                if let trailingImage = TrailingMascotAsset.image {
                    Image(nsImage: trailingImage)
                        .frame(width: 26, height: 26)
                }
            }
            .padding(.horizontal, 8)
            .padding(.top, 4)
            .allowsHitTesting(false)
        }
        .frame(
            width: state.contentWidth,
            alignment: .center
        )
        .fixedSize(horizontal: false, vertical: true)
        .contentShape(Rectangle())
        .onTapGesture { state.onCycleSize?() }
        .contextMenu {
            Button(state.isPaused ? "继续" : "暂停") {
                state.onPause?()
            }
            Button("玻璃模式") {
                state.onGlass?()
            }
            Divider()
            Button("退出") {
                state.onExit?()
            }
        }
    }
}

private struct CompactLeading: View {
    @ObservedObject var state: SubtitleState

    var body: some View {
        Button(action: {
            state.onCycleSize?()
        }) {
            if let mascotImage = MascotAsset.image {
                Image(nsImage: mascotImage)
                    .frame(width: 26, height: 26)
            } else {
                Image(systemName: "captions.bubble.fill")
                    .foregroundStyle(.blue)
            }
        }
        .buttonStyle(.plain)
        .help("点击切换显示 1、2、3 条字幕")
    }
}

private struct CompactTrailing: View {
    @ObservedObject var state: SubtitleState
    var body: some View {
        Button(action: { state.onExit?() }) {
            Image(systemName: "xmark.circle.fill")
                .foregroundStyle(.secondary)
        }
        .buttonStyle(.plain)
    }
}

@main
@MainActor
private struct RealtimeNotchHelper {
    static func main() {
        let app = NSApplication.shared
        app.setActivationPolicy(.accessory)

        let state = SubtitleState()

        func makeNotch(style: DynamicNotchStyle) -> DynamicNotch<
            SubtitleContent, CompactLeading, CompactTrailing
        > {
            DynamicNotch(
                hoverBehavior: [.hapticFeedback, .increaseShadow],
                style: style
            ) {
                SubtitleContent(state: state)
            } compactLeading: {
                CompactLeading(state: state)
            } compactTrailing: {
                CompactTrailing(state: state)
            }
        }

        let physicalNotchStyle = DynamicNotchStyle.notch(
            topCornerRadius: 22,
            bottomCornerRadius: 30
        )
        // One native surface morphs between all display counts. Swapping two
        // independent DynamicNotch instances caused a visible hide/expand warp.
        let notch = makeNotch(style: physicalNotchStyle)
        notch.transitionConfiguration = .init(
            openingAnimation: .easeOut(duration: 0.55),
            closingAnimation: .easeIn(duration: 0.28),
            conversionAnimation: .snappy(duration: 0.32),
            skipIntermediateHides: true
        )

        func expandActiveNotch() async {
            await notch.expand()
        }

        func compactActiveNotch() async {
            await notch.compact()
        }

        func hideNotch() async {
            await notch.hide()
        }

        var terminationInProgress = false
        var lastCycleAt = Date.distantPast
        var notchTransitionTask: Task<Void, Never>?
        func scheduleAutoCompact() {
            state.compactTask?.cancel()
            guard
                state.items.last?.finalized == true,
                !state.hasActiveWork
            else { return }
            let idleSubtitleGeneration = state.subtitleGeneration
            let idleActivityGeneration = state.activityGeneration
            state.compactTask = Task { @MainActor in
                try? await Task.sleep(for: .seconds(6))
                guard
                    !Task.isCancelled,
                    state.subtitleGeneration == idleSubtitleGeneration,
                    state.activityGeneration == idleActivityGeneration,
                    state.items.last?.finalized == true,
                    !state.hasActiveWork
                else { return }
                await compactActiveNotch()
            }
        }

        func compactForPause() {
            state.compactTask?.cancel()
            notchTransitionTask?.cancel()
            notchTransitionTask = Task { @MainActor in
                guard !Task.isCancelled, !terminationInProgress else { return }
                // Pause is an explicit user action: begin the existing
                // animated contraction immediately instead of waiting for
                // the normal finalized-idle timer.
                await compactActiveNotch()
            }
        }

        func terminate(_ event: String) {
            guard !terminationInProgress else { return }
            terminationInProgress = true
            notchTransitionTask?.cancel()
            state.compactTask?.cancel()
            Task { @MainActor in
                await hideNotch()
                // Notify Python only after the reverse contraction finishes;
                // otherwise session shutdown can tear down the helper early.
                emitEvent(event)
                NSApp.terminate(nil)
            }
        }

        state.onExpand = {
            guard !terminationInProgress else { return }
            notchTransitionTask?.cancel()
            notchTransitionTask = Task { @MainActor in
                guard !Task.isCancelled, !terminationInProgress else { return }
                await expandActiveNotch()
            }
        }
        state.onCycleSize = {
            guard !terminationInProgress else { return }
            let now = Date()
            guard now.timeIntervalSince(lastCycleAt) >= 0.25 else { return }
            lastCycleAt = now
            state.cycleSize()
            notchTransitionTask?.cancel()
            notchTransitionTask = Task { @MainActor in
                guard !Task.isCancelled, !terminationInProgress else { return }
                await expandActiveNotch()
            }
        }
        state.onGlass = { terminate("glass") }
        state.onPause = {
            state.isPaused.toggle()
            if state.isPaused {
                compactForPause()
            }
            emitEvent(state.isPaused ? "pause" : "resume")
        }
        state.onExit = { terminate("exit") }

        DispatchQueue.global(qos: .userInitiated).async {
            while let line = readLine() {
                guard let data = line.data(using: .utf8),
                      let message = try? JSONDecoder().decode(InputMessage.self, from: data) else { continue }
                if message.command == "quit" { break }
                Task { @MainActor in
                    guard !terminationInProgress else { return }
                    let wasPaused = state.isPaused
                    if let paused = message.paused {
                        state.isPaused = paused
                        if paused { state.clearActivity() }
                    }
                    if let busyStages = message.busyStages {
                        state.replaceBusyStages(busyStages)
                    }
                    if let items = message.items {
                        let visibleItems = Array(items.suffix(3))
                        var contentTransaction = Transaction()
                        contentTransaction.disablesAnimations = true
                        withTransaction(contentTransaction) {
                            // Stable segment and fragment IDs keep existing rows
                            // alive. Text never inherits the notch frame animation.
                            state.replaceItems(visibleItems)
                        }
                    } else if let original = message.original {
                        var contentTransaction = Transaction()
                        contentTransaction.disablesAnimations = true
                        withTransaction(contentTransaction) {
                            state.replaceItems([SubtitleLine(
                                id: 0,
                                original: original,
                                translated: message.translated ?? "",
                                finalized: true,
                                committedPrefixLength: 0,
                                fragments: nil
                            )])
                        }
                    }
                    state.compactTask?.cancel()
                    if state.isPaused {
                        // The local context-menu action already started the
                        // transition. Avoid cancelling and restarting it when
                        // Python acknowledges the same pause state.
                        if !wasPaused {
                            compactForPause()
                        }
                    } else if state.hasSubtitleContent {
                        await expandActiveNotch()
                        scheduleAutoCompact()
                    } else {
                        // Runtime status frames arrive during initialization.
                        // They must not expand an empty notch before speech.
                        await compactActiveNotch()
                    }
                }
            }
            DispatchQueue.main.async {
                Task { @MainActor in
                    await hideNotch()
                    NSApp.terminate(nil)
                }
            }
        }

        // With no speech yet, grow directly from hidden into the unobtrusive
        // compact notch. Actual subtitle content expands to the saved size.
        state.compactTask = Task { @MainActor in
            try? await Task.sleep(for: .seconds(0.06))
            guard !Task.isCancelled else { return }
            await compactActiveNotch()
        }
        app.run()
    }
}
