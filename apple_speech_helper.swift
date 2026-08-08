import AVFoundation
import Foundation
import Speech

@available(macOS 26.0, *)
private func emit(_ payload: [String: Any]) {
    guard let data = try? JSONSerialization.data(withJSONObject: payload) else { return }
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data([0x0A]))
}

@available(macOS 26.0, *)
private func makeBuffer(from data: Data, format: AVAudioFormat) -> AVAudioPCMBuffer? {
    let frameCount = AVAudioFrameCount(data.count / MemoryLayout<Int16>.size)
    guard frameCount > 0,
          let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: frameCount),
          let destination = buffer.int16ChannelData?[0] else {
        return nil
    }
    buffer.frameLength = frameCount
    data.copyBytes(
        to: UnsafeMutableRawBufferPointer(
            start: destination,
            count: Int(frameCount) * MemoryLayout<Int16>.size
        )
    )
    return buffer
}

@main
struct AppleSpeechHelper {
    static func main() async {
        guard #available(macOS 26.0, *) else {
            fputs("Apple SpeechTranscriber requires macOS 26 or newer.\n", stderr)
            exit(2)
        }

        let arguments = CommandLine.arguments
        let localeID = arguments.count > 1 ? arguments[1] : "en-US"
        let sampleRate = arguments.count > 2 ? Double(arguments[2]) ?? 16_000 : 16_000

        do {
            guard SpeechTranscriber.isAvailable else {
                throw NSError(domain: "AppleSpeechHelper", code: 1,
                              userInfo: [NSLocalizedDescriptionKey: "SpeechTranscriber is unavailable"])
            }
            guard let locale = await SpeechTranscriber.supportedLocale(
                equivalentTo: Locale(identifier: localeID)
            ) else {
                throw NSError(domain: "AppleSpeechHelper", code: 2,
                              userInfo: [NSLocalizedDescriptionKey: "Unsupported locale: \(localeID)"])
            }

            let transcriber = SpeechTranscriber(
                locale: locale,
                transcriptionOptions: [],
                reportingOptions: [.volatileResults, .fastResults],
                attributeOptions: []
            )

            if await AssetInventory.status(forModules: [transcriber]) != .installed {
                if let request = try await AssetInventory.assetInstallationRequest(
                    supporting: [transcriber]
                ) {
                    emit(["type": "status", "status": "downloading_assets"])
                    try await request.downloadAndInstall()
                }
            }

            guard let inputFormat = AVAudioFormat(
                commonFormat: .pcmFormatInt16,
                sampleRate: sampleRate,
                channels: 1,
                interleaved: false
            ) else {
                throw NSError(domain: "AppleSpeechHelper", code: 3,
                              userInfo: [NSLocalizedDescriptionKey: "Cannot create input audio format"])
            }

            let compatibleFormats = await transcriber.availableCompatibleAudioFormats
            guard compatibleFormats.contains(where: {
                $0.sampleRate == inputFormat.sampleRate &&
                $0.channelCount == inputFormat.channelCount &&
                $0.commonFormat == inputFormat.commonFormat
            }) else {
                let formats = compatibleFormats.map {
                    "\(Int($0.sampleRate))Hz/\($0.channelCount)ch/\($0.commonFormat.rawValue)"
                }.joined(separator: ", ")
                throw NSError(domain: "AppleSpeechHelper", code: 4,
                              userInfo: [NSLocalizedDescriptionKey:
                                "Input format \(Int(sampleRate))Hz int16 unsupported; available: \(formats)"])
            }

            let analyzer = SpeechAnalyzer(modules: [transcriber])
            try await analyzer.prepareToAnalyze(in: inputFormat)

            let (inputStream, continuation) = AsyncStream.makeStream(of: AnalyzerInput.self)

            let resultTask = Task {
                for try await result in transcriber.results {
                    let text = String(result.text.characters).trimmingCharacters(in: .whitespacesAndNewlines)
                    guard !text.isEmpty else { continue }
                    emit([
                        "type": "result",
                        "text": text,
                        "final": result.isFinal
                    ])
                }
            }

            emit([
                "type": "status",
                "status": "ready",
                "locale": locale.identifier,
                "sample_rate": Int(sampleRate)
            ])

            let inputTask = Task.detached {
                var pending = Data()
                while true {
                    let data = FileHandle.standardInput.availableData
                    if data.isEmpty { break }
                    pending.append(data)
                    let usableBytes = pending.count - (pending.count % MemoryLayout<Int16>.size)
                    guard usableBytes > 0 else { continue }
                    let audioData = pending.prefix(usableBytes)
                    pending.removeFirst(usableBytes)
                    if let buffer = makeBuffer(from: Data(audioData), format: inputFormat) {
                        continuation.yield(AnalyzerInput(buffer: buffer))
                    }
                }
                continuation.finish()
            }

            _ = try await analyzer.analyzeSequence(inputStream)
            try await analyzer.finalizeAndFinishThroughEndOfInput()
            _ = await inputTask.result
            _ = try await resultTask.value
            emit(["type": "status", "status": "finished"])
        } catch {
            emit(["type": "error", "message": error.localizedDescription])
            fputs("Apple Speech helper error: \(error)\n", stderr)
            exit(1)
        }
    }
}
