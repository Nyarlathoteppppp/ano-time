import AppKit
import DynamicNotchKit
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
}

private struct SubtitleLine: Codable, Identifiable {
    let id: Int
    let original: String
    let translated: String
    let finalized: Bool?
}

@MainActor
private final class SubtitleState: ObservableObject {
    private static let sizeDefaults = UserDefaults(
        suiteName: "com.nyarlathotep.realtime-ton.notch"
    )

    @Published var items = [
        SubtitleLine(id: 0, original: "Waiting for speech…", translated: "", finalized: false)
    ] {
        didSet { refreshContentWidth() }
    }
    @Published var displayCount: Int
    @Published private(set) var contentWidth: CGFloat = 360
    @Published var isPaused = false
    var compactTask: Task<Void, Never>?
    private var widthShrinkTask: Task<Void, Never>?
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
        }
    }

    private func measuredContentWidth() -> CGFloat {
        let visibleItems = items.suffix(displayCount)
        let englishFont = NSFont.systemFont(ofSize: 11.5, weight: .regular)
        let translatedFont = NSFont.systemFont(ofSize: 16, weight: .semibold)
        let measured = visibleItems.reduce(CGFloat(0)) { longest, item in
            let hidesOriginal = displayCount == 1 || (
                displayCount == 3 && item.id == visibleItems.first?.id
            )
            let englishWidth = hidesOriginal ? 0 : (item.original as NSString).size(
                withAttributes: [.font: englishFont]
            ).width
            let translatedWidth = (item.translated as NSString).size(
                withAttributes: [.font: translatedFont]
            ).width
            return max(longest, max(englishWidth, translatedWidth))
        }
        let minimumWidth: CGFloat = 360
        let maximumWidth: CGFloat = 560
        let widthStep: CGFloat = 20
        // Reserve equal space for the two edge mascots so subtitles remain
        // centered and never run underneath either image.
        let desired = max(minimumWidth, measured + 80)
        let stepped = ceil(desired / widthStep) * widthStep
        return min(maximumWidth, stepped)
    }

    private func setContentWidth(_ width: CGFloat, animated: Bool) {
        guard width != contentWidth else { return }
        let isShrinking = width < contentWidth
        if animated && isShrinking {
            withAnimation(.easeInOut(duration: 0.45)) {
                contentWidth = width
            }
        } else {
            contentWidth = width
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
        widthShrinkTask?.cancel()

        if targetWidth >= contentWidth || allowImmediateShrink {
            setContentWidth(targetWidth, animated: animated)
            return
        }

        // Growing text must never be clipped. Shrinking is intentionally
        // delayed so partial-ASR corrections do not make the notch breathe.
        widthShrinkTask = Task { @MainActor [weak self] in
            try? await Task.sleep(for: .seconds(1.2))
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

private struct SubtitleContent: View {
    @ObservedObject var state: SubtitleState

    var body: some View {
        ZStack(alignment: .top) {
            VStack(alignment: .center, spacing: 5) {
                ForEach(state.items.suffix(state.displayCount)) { item in
                    VStack(alignment: .center, spacing: 2) {
                        let hidesOriginal = state.displayCount == 1 || (
                            state.displayCount == 3
                                && item.id == state.items.suffix(3).first?.id
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

                        Text(item.translated.isEmpty ? "…" : item.translated)
                            .font(.system(size: 16, weight: .semibold))
                            .foregroundStyle(.white)
                            .lineLimit(2)
                            .multilineTextAlignment(.center)
                            .frame(maxWidth: .infinity, alignment: .center)
                    }
                    .frame(maxWidth: .infinity, alignment: .center)
                    .transition(.opacity)
                }
            }
            .padding(.horizontal, 40)

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
        func terminate(_ event: String) {
            guard !terminationInProgress else { return }
            terminationInProgress = true
            Task { @MainActor in
                await hideNotch()
                // Notify Python only after the reverse contraction finishes;
                // otherwise session shutdown can tear down the helper early.
                emitEvent(event)
                NSApp.terminate(nil)
            }
        }

        state.onExpand = { Task { @MainActor in await expandActiveNotch() } }
        state.onCycleSize = {
            state.cycleSize()
            Task { @MainActor in
                await expandActiveNotch()
            }
        }
        state.onGlass = { terminate("glass") }
        state.onPause = {
            state.isPaused.toggle()
            emitEvent(state.isPaused ? "pause" : "resume")
        }
        state.onExit = { terminate("exit") }

        DispatchQueue.global(qos: .userInitiated).async {
            while let line = readLine() {
                guard let data = line.data(using: .utf8),
                      let message = try? JSONDecoder().decode(InputMessage.self, from: data) else { continue }
                if message.command == "quit" { break }
                Task { @MainActor in
                    if let paused = message.paused {
                        state.isPaused = paused
                    }
                    withAnimation(.easeOut(duration: 0.14)) {
                        if let items = message.items, !items.isEmpty {
                            state.items = Array(items.suffix(3))
                        } else if let original = message.original {
                            state.items = [SubtitleLine(
                                id: 0,
                                original: original,
                                translated: message.translated ?? "",
                                finalized: true
                            )]
                        }
                    }
                    state.compactTask?.cancel()
                    await expandActiveNotch()
                    state.compactTask = Task { @MainActor in
                        try? await Task.sleep(for: .seconds(6))
                        guard !Task.isCancelled else { return }
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
