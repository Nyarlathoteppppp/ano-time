import Foundation
import Translation

private func emit(_ payload: [String: Any]) {
    guard let data = try? JSONSerialization.data(withJSONObject: payload) else { return }
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data([0x0A]))
}

@available(macOS 26.0, *)
private func processLine(_ line: Data, session: TranslationSession) async {
    do {
        guard let request = try JSONSerialization.jsonObject(with: line) as? [String: Any],
              let id = request["id"] as? Int,
              let text = request["text"] as? String else {
            throw NSError(domain: "AppleTranslationHelper", code: 2,
                          userInfo: [NSLocalizedDescriptionKey: "Invalid JSON request"])
        }
        let response = try await session.translate(text)
        emit(["type": "result", "id": id, "text": response.targetText])
    } catch {
        // A malformed or temporarily unavailable *request* must not poison the
        // persistent session.  Python can reject only this id and keep using
        // the already-ready Apple Translation helper for the next subtitle.
        emit([
            "type": "request_error",
            "id": requestID(from: line) ?? -1,
            "message": error.localizedDescription,
        ])
    }
}

private func requestID(from line: Data) -> Int? {
    guard let request = try? JSONSerialization.jsonObject(with: line) as? [String: Any] else {
        return nil
    }
    return request["id"] as? Int
}

@main
struct AppleTranslationHelper {
    static func main() async {
        guard #available(macOS 26.0, *) else {
            emit(["type": "error", "message": "Apple Translation requires macOS 26 or newer"])
            exit(2)
        }

        let arguments = CommandLine.arguments
        let sourceID = arguments.count > 1 ? arguments[1] : "en"
        let targetID = arguments.count > 2 ? arguments[2] : "zh-Hans"
        let source = Locale.Language(identifier: sourceID)
        let target = Locale.Language(identifier: targetID)

        let availability = LanguageAvailability()
        let status = await availability.status(from: source, to: target)
        guard status != .unsupported else {
            emit(["type": "error", "message": "Unsupported language pair: \(sourceID) -> \(targetID)"])
            exit(3)
        }

        let session = TranslationSession(installedSource: source, target: target)
        do {
            if !(await session.isReady) {
                emit(["type": "status", "status": "preparing_languages"])
                try await session.prepareTranslation()
            }
            emit(["type": "status", "status": "ready"])

            var pending = Data()
            while true {
                let data = FileHandle.standardInput.availableData
                if data.isEmpty { break }
                pending.append(data)
                while let newline = pending.firstIndex(of: 0x0A) {
                    let line = pending.prefix(upTo: newline)
                    pending.removeSubrange(...newline)
                    if !line.isEmpty {
                        await processLine(Data(line), session: session)
                    }
                }
            }
        } catch {
            emit(["type": "error", "message": error.localizedDescription])
            exit(1)
        }
    }
}
