import AppKit
import DynamicNotchKit
import SwiftUI

private struct InputMessage: Decodable {
    let command: String?
    let original: String?
    let translated: String?
    let items: [SubtitleLine]?
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
    ]
    @Published var displayCount: Int
    var compactTask: Task<Void, Never>?
    var onExpand: (() -> Void)?
    var onCycleSize: (() -> Void)?
    var onGlass: (() -> Void)?
    var onExit: (() -> Void)?

    init() {
        let saved = Self.sizeDefaults?.integer(forKey: "displayCount") ?? 0
        displayCount = (1...3).contains(saved) ? saved : 2
    }

    func cycleSize() {
        displayCount = displayCount == 3 ? 1 : displayCount + 1
        Self.sizeDefaults?.set(displayCount, forKey: "displayCount")
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
        VStack(alignment: .leading, spacing: 5) {
            ForEach(state.items.suffix(state.displayCount)) { item in
                VStack(alignment: .leading, spacing: 2) {
                    Text(item.original)
                        .font(.system(
                            size: 11.5,
                            weight: item.finalized == true ? .medium : .regular
                        ))
                        .foregroundStyle(
                            .white.opacity(item.finalized == true ? 0.96 : 0.78)
                        )
                        .lineLimit(1)

                    Text(item.translated.isEmpty ? "…" : item.translated)
                        .font(.system(size: 16, weight: .semibold))
                        .foregroundStyle(.white)
                        .lineLimit(2)
                }
            }
        }
        .frame(
            width: state.displayCount == 1 ? 380 : (state.displayCount == 2 ? 460 : 540),
            alignment: .leading
        )
        .fixedSize(horizontal: false, vertical: true)
        .contentShape(Rectangle())
        .onTapGesture { state.onCycleSize?() }
        .animation(.easeInOut(duration: 0.18), value: state.displayCount)
    }
}

private struct CompactLeading: View {
    @ObservedObject var state: SubtitleState
    var body: some View {
        Button(action: {
            state.onCycleSize?()
        }) {
            Image(systemName: "captions.bubble.fill")
                .foregroundStyle(.blue)
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

        let regularNotch = makeNotch(style: .auto)
        // One-line mode uses matching upper/lower radii so both sides form a
        // capsule. Medium and large retain DynamicNotchKit's normal silhouette.
        let smallNotch = makeNotch(style: .notch(
            topCornerRadius: 48,
            bottomCornerRadius: 48
        ))

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
        state.onExit = { terminate("exit") }

        DispatchQueue.global(qos: .userInitiated).async {
            while let line = readLine() {
                guard let data = line.data(using: .utf8),
                      let message = try? JSONDecoder().decode(InputMessage.self, from: data) else { continue }
                if message.command == "quit" { break }
                Task { @MainActor in
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
