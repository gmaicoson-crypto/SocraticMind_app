import Foundation
import MindCore

/// Owns only a temporary synthetic server; it cannot reuse the user's database or model settings.
final class LoopbackFixture {
    let endpoint: APIEndpoint
    private let process: Process
    private let directory: URL

    init() throws {
        var root = URL(fileURLWithPath: #filePath)
        for _ in 0 ..< 6 {
            root.deleteLastPathComponent()
        }
        directory = FileManager.default.temporaryDirectory.appendingPathComponent("socratic-http-\(UUID())")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let ready = directory.appendingPathComponent("ready.json")
        process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        process.arguments = ["python3", root.appendingPathComponent("scripts/contracts/transport_fixture.py").path,
                             "--ready-file", ready.path]
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        do {
            try process.run()
            let deadline = Date().addingTimeInterval(10)
            while !FileManager.default.fileExists(atPath: ready.path), process.isRunning, Date() < deadline {
                Thread.sleep(forTimeInterval: 0.02)
            }
            let response = try JSONDecoder().decode(Ready.self, from: Data(contentsOf: ready))
            endpoint = try APIEndpoint(response.url, developmentHTTPHosts: ["127.0.0.1"])
        } catch {
            if process.isRunning {
                process.terminate(); process.waitUntilExit()
            }
            try? FileManager.default.removeItem(at: directory)
            throw error
        }
    }

    func close() {
        if process.isRunning {
            process.terminate(); process.waitUntilExit()
        }
        try? FileManager.default.removeItem(at: directory)
    }

    private struct Ready: Decodable { let url: String }
}

actor EventRecorder {
    private var events: [ChatEvent] = []
    func append(_ event: ChatEvent) {
        events.append(event)
    }

    func snapshot() -> [ChatEvent] {
        events
    }
}
