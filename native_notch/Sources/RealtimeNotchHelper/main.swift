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

    var sizeTitle: String {
        switch displayCount {
        case 1: return "小 · 1条"
        case 2: return "中 · 2条"
        default: return "大 · 3条"
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
        VStack(alignment: .leading, spacing: 5) {
            HStack(spacing: 8) {
                Button(action: { state.onCycleSize?() }) {
                    Label(state.sizeTitle, systemImage: "rectangle.3.group")
                }
                .buttonStyle(.borderless)
                .foregroundStyle(.secondary)
                .help("点击切换小、中、大刘海字幕")
                Spacer()
                Button("Glass") { state.onGlass?() }
                    .buttonStyle(.borderless)
                    .foregroundStyle(.secondary)
                Button("Exit") { state.onExit?() }
                    .buttonStyle(.borderless)
                    .foregroundStyle(.red)
            }
            .font(.system(size: 11, weight: .medium))

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
                        .animation(.easeOut(duration: 0.12), value: item.finalized)

                    if !item.translated.isEmpty {
                        Text(item.translated)
                            .font(.system(size: 16, weight: .semibold))
                            .foregroundStyle(.white)
                            .lineLimit(2)
                    }
                }
                .contentShape(Rectangle())
                .onTapGesture { state.onCycleSize?() }
            }

        }
        .frame(
            width: state.displayCount == 1 ? 380 : (state.displayCount == 2 ? 460 : 540),
            alignment: .leading
        )
        .fixedSize(horizontal: false, vertical: true)
        .animation(.easeInOut(duration: 0.18), value: state.displayCount)
    }
}

private struct CompactLeading: View {
    @ObservedObject var state: SubtitleState
    var body: some View {
        Button(action: {
            state.onCycleSize?()
        }) {
            HStack(spacing: 4) {
                Image(systemName: "captions.bubble.fill")
                Text("\(state.displayCount)")
                    .font(.system(size: 10, weight: .bold, design: .rounded))
            }
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
        let notch = DynamicNotch(style: .auto) {
            SubtitleContent(state: state)
        } compactLeading: {
            CompactLeading(state: state)
        } compactTrailing: {
            CompactTrailing(state: state)
        }

        func terminate(_ event: String) {
            emitEvent(event)
            Task { @MainActor in
                await notch.hide()
                NSApp.terminate(nil)
            }
        }

        state.onExpand = { Task { @MainActor in await notch.expand() } }
        state.onCycleSize = {
            state.cycleSize()
            Task { @MainActor in await notch.expand() }
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
                    await notch.expand()
                    state.compactTask?.cancel()
                    state.compactTask = Task { @MainActor in
                        try? await Task.sleep(for: .seconds(6))
                        guard !Task.isCancelled else { return }
                        await notch.compact()
                    }
                }
            }
            DispatchQueue.main.async {
                Task { @MainActor in
                    await notch.hide()
                    NSApp.terminate(nil)
                }
            }
        }

        Task { @MainActor in await notch.compact() }
        app.run()
    }
}
