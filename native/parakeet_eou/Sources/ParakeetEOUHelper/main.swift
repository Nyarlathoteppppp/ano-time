import AVFoundation
import CoreML
import FluidAudio
import Foundation

private let sampleRate = 16_000.0

private func eouDebounceMs() -> Int {
    let arguments = CommandLine.arguments
    guard let index = arguments.firstIndex(of: "--eou-debounce-ms"),
          arguments.indices.contains(index + 1),
          let value = Int(arguments[index + 1]),
          [320, 480, 640, 800].contains(value)
    else { return 640 }
    return value
}

private func emit(_ type: String, _ values: [String: Any] = [:]) {
    var payload = values
    payload["type"] = type
    guard let data = try? JSONSerialization.data(withJSONObject: payload) else { return }
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data([0x0A]))
}

private func pcmBuffer(from data: Data) -> AVAudioPCMBuffer? {
    let frameCount = AVAudioFrameCount(data.count / MemoryLayout<Int16>.size)
    guard frameCount > 0,
          let format = AVAudioFormat(
              commonFormat: .pcmFormatInt16,
              sampleRate: sampleRate,
              channels: 1,
              interleaved: false
          ),
          let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: frameCount),
          let destination = buffer.int16ChannelData?[0]
    else { return nil }
    buffer.frameLength = frameCount
    data.copyBytes(to: UnsafeMutableRawBufferPointer(
        start: destination,
        count: Int(frameCount) * MemoryLayout<Int16>.size
    ))
    return buffer
}

@main
struct ParakeetEOUHelper {
    static func main() async {
        let configuration = MLModelConfiguration()
        configuration.computeUnits = .all
        let manager = StreamingEouAsrManager(
            configuration: configuration,
            chunkSize: .ms160,
            eouDebounceMs: eouDebounceMs()
        )

        await manager.setPartialTranscriptCallback { text in
            guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
            emit("result", ["text": text, "final": false])
        }

        do {
            try await manager.loadModels()
            emit("status", ["status": "ready", "sample_rate": Int(sampleRate)])

            var pending = Data()
            while true {
                let data = FileHandle.standardInput.availableData
                if data.isEmpty { break }
                pending.append(data)
                let usableBytes = pending.count - (pending.count % MemoryLayout<Int16>.size)
                guard usableBytes > 0 else { continue }
                let pcm = Data(pending.prefix(usableBytes))
                pending.removeFirst(usableBytes)
                guard let buffer = pcmBuffer(from: pcm) else { continue }
                try await manager.appendAudio(buffer)
                try await manager.processBufferedAudio()

                if await manager.eouDetected {
                    let text = await manager.getPartialTranscript()
                    if !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                        emit("result", ["text": text, "final": true])
                    }
                    try await manager.reset()
                }
            }

            // Use normal silence rather than `finish()`: the upstream EOU
            // package's short-tail padding path is currently unstable, whereas
            // its regular EOU path is what a live microphone uses.
            await manager.injectSilence(1.0)
            try await manager.processBufferedAudio()
            let tail = await manager.getPartialTranscript()
            if !tail.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                emit("result", ["text": tail, "final": true])
            }
            await manager.cleanup()
            emit("status", ["status": "finished"])
        } catch {
            emit("error", ["message": String(describing: error)])
            fputs("Parakeet EOU helper error: \(error)\n", stderr)
            exit(1)
        }
    }
}
