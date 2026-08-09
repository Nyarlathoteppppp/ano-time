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
        displayCount = displayCount == 3 ? 1 : displayCount + 1
        Self.sizeDefaults?.set(displayCount, forKey: "displayCount")
        refreshContentWidth(allowImmediateShrink: true)
    }

    private func measuredContentWidth() -> CGFloat {
        let visibleItems = items.suffix(displayCount)
        let englishFont = NSFont.systemFont(ofSize: 11.5, weight: .regular)
        let translatedFont = NSFont.systemFont(ofSize: 16, weight: .semibold)
        let measured = visibleItems.reduce(CGFloat(0)) { longest, item in
            let englishWidth = (item.original as NSString).size(
                withAttributes: [.font: englishFont]
            ).width
            let translatedWidth = (item.translated as NSString).size(
                withAttributes: [.font: translatedFont]
            ).width
            return max(longest, max(englishWidth, translatedWidth))
        }
        let minimumWidth: CGFloat = 360
        let maximumWidth: CGFloat = 560
        let widthStep: CGFloat = 40
        // Reserve equal space on both sides so the expanded mascot can sit on
        // the left without moving the centered subtitles or covering text.
        let desired = max(minimumWidth, measured + 80)
        let stepped = ceil(desired / widthStep) * widthStep
        return min(maximumWidth, stepped)
    }

    private func refreshContentWidth(allowImmediateShrink: Bool = false) {
        let targetWidth = measuredContentWidth()
        widthShrinkTask?.cancel()

        if targetWidth >= contentWidth || allowImmediateShrink {
            contentWidth = targetWidth
            return
        }

        // Growing text must never be clipped. Shrinking is intentionally
        // delayed so partial-ASR corrections do not make the notch breathe.
        widthShrinkTask = Task { @MainActor [weak self] in
            try? await Task.sleep(for: .seconds(1.2))
            guard let self, !Task.isCancelled else { return }
            let latestTarget = self.measuredContentWidth()
            if latestTarget < self.contentWidth {
                self.contentWidth = latestTarget
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

    private var visibleItemIDs: [Int] {
        state.items.suffix(state.displayCount).map(\.id)
    }

    var body: some View {
        ZStack(alignment: .topTrailing) {
            VStack(alignment: .center, spacing: 5) {
                ForEach(state.items.suffix(state.displayCount)) { item in
                    VStack(alignment: .center, spacing: 2) {
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

                        Text(item.translated.isEmpty ? "…" : item.translated)
                            .font(.system(size: 16, weight: .semibold))
                            .foregroundStyle(.white)
                            .lineLimit(2)
                            .multilineTextAlignment(.center)
                            .frame(maxWidth: .infinity, alignment: .center)
                    }
                    .frame(maxWidth: .infinity, alignment: .center)
                    .transition(.asymmetric(
                        insertion: .opacity.combined(with: .move(edge: .bottom)),
                        removal: .opacity.combined(with: .move(edge: .top))
                    ))
                }
            }
            .padding(.horizontal, 40)

            if let mascotImage = MascotAsset.image {
                Image(nsImage: mascotImage)
                    .frame(width: 26, height: 26)
                    .padding(.top, 4)
                    .padding(.trailing, 8)
                    .allowsHitTesting(false)
            }
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
        .animation(.easeInOut(duration: 0.18), value: state.displayCount)
        .animation(.easeInOut(duration: 0.16), value: state.contentWidth)
        .animation(.easeInOut(duration: 0.22), value: visibleItemIDs)
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
            DynamicNotch(style: style) {
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
        // All three sizes keep the same softened physical-notch silhouette;
        // only their content height and visible subtitle count differ.
        let regularNotch = makeNotch(style: physicalNotchStyle)
        let smallNotch = makeNotch(style: physicalNotchStyle)

        func expandActiveNotch() async {
            if state.displayCount == 1 {
                await smallNotch.expand()
            } else {
                await regularNotch.expand()
            }
        }

        func compactActiveNotch() async {
            if state.displayCount == 1 {
                await smallNotch.compact()
            } else {
                await regularNotch.compact()
            }
        }

        func hideBothNotches() async {
            await smallNotch.hide()
            await regularNotch.hide()
        }

        func terminate(_ event: String) {
            emitEvent(event)
            Task { @MainActor in
                await hideBothNotches()
                NSApp.terminate(nil)
            }
        }

        state.onExpand = { Task { @MainActor in await expandActiveNotch() } }
        state.onCycleSize = {
            let previousCount = state.displayCount
            state.cycleSize()
            Task { @MainActor in
                if previousCount == 1 && state.displayCount != 1 {
                    await smallNotch.hide()
                } else if previousCount != 1 && state.displayCount == 1 {
                    await regularNotch.hide()
                }
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
                    await expandActiveNotch()
                    state.compactTask?.cancel()
                    state.compactTask = Task { @MainActor in
                        try? await Task.sleep(for: .seconds(6))
                        guard !Task.isCancelled else { return }
                        await compactActiveNotch()
                    }
                }
            }
            DispatchQueue.main.async {
                Task { @MainActor in
                    await hideBothNotches()
                    NSApp.terminate(nil)
                }
            }
        }

        Task { @MainActor in await compactActiveNotch() }
        app.run()
    }
}
