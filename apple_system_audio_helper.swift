import AVFoundation
import CoreMedia
import Foundation
import ScreenCaptureKit

private func log(_ message: String) {
    FileHandle.standardError.write(Data((message + "\n").utf8))
}

private final class AudioOutput: NSObject, SCStreamOutput, SCStreamDelegate, @unchecked Sendable {
    private let output = FileHandle.standardOutput
    private let writeQueue = DispatchQueue(label: "realtime-ton.system-audio.write")
    private var loggedFormat = false

    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer,
                of outputType: SCStreamOutputType) {
        guard outputType == .audio, sampleBuffer.isValid,
              CMSampleBufferDataIsReady(sampleBuffer) else { return }

        if !loggedFormat,
           let description = sampleBuffer.formatDescription,
           let asbd = CMAudioFormatDescriptionGetStreamBasicDescription(description)?.pointee {
            loggedFormat = true
            log("Format: \(Int(asbd.mSampleRate)) Hz, \(asbd.mChannelsPerFrame) ch, " +
                "format=\(asbd.mFormatID), flags=\(asbd.mFormatFlags)")
        }

        do {
            try sampleBuffer.withAudioBufferList { audioBufferList, _ in
                for buffer in audioBufferList {
                    guard let pointer = buffer.mData, buffer.mDataByteSize > 0 else { continue }
                    let data = Data(bytes: pointer, count: Int(buffer.mDataByteSize))
                    writeQueue.sync { output.write(data) }
                }
            }
        } catch {
            log("Unable to read audio sample: \(error)")
        }
    }

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        log("Capture stopped with error: \(error.localizedDescription)")
        exit(2)
    }
}

@main
private struct SystemAudioHelper {
    static func main() async {
        let requestedRate = CommandLine.arguments.dropFirst().first.flatMap(Int.init) ?? 16_000

        do {
            let content = try await SCShareableContent.excludingDesktopWindows(
                false, onScreenWindowsOnly: true
            )
            guard let display = content.displays.first else {
                log("No display is available for system-audio capture")
                exit(2)
            }

            let filter = SCContentFilter(
                display: display, excludingApplications: [], exceptingWindows: []
            )
            let configuration = SCStreamConfiguration()
            configuration.capturesAudio = true
            configuration.excludesCurrentProcessAudio = true
            configuration.sampleRate = requestedRate
            configuration.channelCount = 1
            configuration.width = 2
            configuration.height = 2
            configuration.minimumFrameInterval = CMTime(value: 1, timescale: 1)

            let output = AudioOutput()
            let stream = SCStream(filter: filter, configuration: configuration, delegate: output)
            try stream.addStreamOutput(
                output,
                type: .audio,
                sampleHandlerQueue: DispatchQueue(label: "realtime-ton.system-audio.capture")
            )
            try await stream.startCapture()
            log("Ready — capturing system audio. Permission: Screen & System Audio Recording")

            await withCheckedContinuation { (continuation: CheckedContinuation<Void, Never>) in
                DispatchQueue.global(qos: .utility).async {
                    while let line = readLine(), line != "quit" {}
                    continuation.resume()
                }
            }
            try await stream.stopCapture()
        } catch {
            log("Failed to start: \(error.localizedDescription)")
            log("Open System Settings > Privacy & Security > Screen & System Audio Recording, " +
                "allow Terminal/Python, then restart the app.")
            exit(2)
        }
    }
}
