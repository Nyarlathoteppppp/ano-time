import AppKit
import DynamicNotchKit
import SwiftUI

private struct InputMessage: Decodable {
    let command: String?
    let original: String?
    let translated: String?
}

@MainActor
private final class SubtitleState: ObservableObject {
    @Published var original = "Waiting for speech…"
    @Published var translated = ""
    @Published var generation = 0
    var onExpand: (() -> Void)?
    var onGlass: (() -> Void)?
    var onExit: (() -> Void)?
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
        VStack(alignment: .leading, spacing: 7) {
            Text(state.original)
                .font(.system(size: 13, weight: .regular))
                .foregroundStyle(.secondary)
                .lineLimit(2)

            if !state.translated.isEmpty {
                Text(state.translated)
                    .font(.system(size: 20, weight: .semibold))
                    .foregroundStyle(.white)
                    .lineLimit(3)
            }

            HStack(spacing: 8) {
                Spacer()
                Button("Glass") { state.onGlass?() }
                    .buttonStyle(.borderless)
                    .foregroundStyle(.secondary)
                Button("Exit") { state.onExit?() }
                    .buttonStyle(.borderless)
                    .foregroundStyle(.red)
            }
            .font(.system(size: 12, weight: .medium))
        }
        .frame(width: 540, alignment: .leading)
    }
}

private struct CompactLeading: View {
    @ObservedObject var state: SubtitleState
    var body: some View {
        Button(action: { state.onExpand?() }) {
            Image(systemName: "captions.bubble.fill")
                .foregroundStyle(.blue)
        }
        .buttonStyle(.plain)
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
        state.onGlass = { terminate("glass") }
        state.onExit = { terminate("exit") }

        DispatchQueue.global(qos: .userInitiated).async {
            while let line = readLine() {
                guard let data = line.data(using: .utf8),
                      let message = try? JSONDecoder().decode(InputMessage.self, from: data) else { continue }
                if message.command == "quit" { break }
                Task { @MainActor in
                    if let original = message.original, !original.isEmpty { state.original = original }
                    if let translated = message.translated { state.translated = translated }
                    state.generation += 1
                    let currentGeneration = state.generation
                    await notch.expand()
                    try? await Task.sleep(for: .seconds(6))
                    if state.generation == currentGeneration { await notch.compact() }
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
