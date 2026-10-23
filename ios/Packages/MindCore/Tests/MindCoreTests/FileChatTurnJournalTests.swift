import Foundation
@testable import MindCore
import Testing

struct FileChatTurnJournalTests {
    @Test
    func schemaOneRemainsReadableAndRegenerationSurvivesSchemaTwoReopen() async throws {
        try await withDirectory { directory in
            let journal = try FileChatTurnJournal(directory: directory, endpointScope: "scope")
            let ordinary = try turnRequest().pending
            try await journal.save(ordinary)
            let file = try #require(records(directory).first)
            let legacy = try String(contentsOf: file, encoding: .utf8).replacingOccurrences(
                of: "\"schema\":2",
                with: "\"schema\":1"
            )
            try Data(legacy.utf8).write(to: file)
            #expect(try await journal.read(ownerID: 1) == ordinary)
            try await journal.clear(ordinary)
            let pending = try PendingChatTurn(
                ownerID: 1,
                target: ordinary.target,
                requestID: ordinary.requestID,
                regenerateMessageID: 102
            )
            try await journal.save(pending)
            #expect(try String(contentsOf: file, encoding: .utf8).contains("\"schema\":2"))
            #expect(try await FileChatTurnJournal(directory: directory, endpointScope: "scope")
                .read(ownerID: 1) == pending)
            await #expect(throws: ChatTurnFailure.self) { try await journal.clear(ordinary) }
            #expect(try await journal.read(ownerID: 1) == pending)
        }
    }

    @Test
    func reopenPersistsOnlyIdentifiersWithEndpointAndOwnerIsolation() async throws {
        try await withDirectory { directory in
            let pending = try turnRequest().pending
            let journal = try FileChatTurnJournal(directory: directory, endpointScope: "https://example.test/")
            try await journal.save(pending)
            let second = try PendingChatTurn(ownerID: 2, target: pending.target, requestID: "other")
            try await journal.save(second)
            #expect(try await FileChatTurnJournal(directory: directory, endpointScope: "https://example.test/")
                .read(ownerID: 1) == pending)
            #expect(try await journal.read(ownerID: 2) == second)
            #expect(try await FileChatTurnJournal(directory: directory, endpointScope: "https://other.test/")
                .read(ownerID: 1) == nil)
            let files = try records(directory)
            #expect(files.count == 2)
            for file in files {
                let content = try String(contentsOf: file, encoding: .utf8)
                #expect(!content.contains("user_input") && !content.contains("access_token") && !content
                    .contains("为什么"))
            }
            try await journal.clear(pending)
            #expect(try await journal.read(ownerID: 1) == nil)
            #expect(try await journal.read(ownerID: 2) == second)
        }
    }

    @Test
    func differentSaveAndStaleClearCannotErasePendingRecord() async throws {
        try await withDirectory { directory in
            let journal = try FileChatTurnJournal(directory: directory, endpointScope: "scope")
            let pending = try turnRequest().pending
            try await journal.save(pending)
            try await journal.save(pending)
            let newer = try PendingChatTurn(ownerID: 1, target: pending.target, requestID: "different")
            await #expect(throws: ChatTurnFailure.self) { try await journal.save(newer) }
            await #expect(throws: ChatTurnFailure.self) { try await journal.clear(newer) }
            #expect(try await journal.read(ownerID: 1) == pending)
        }
    }

    @Test
    func corruptOversizedAndOwnerMismatchFailClosed() async throws {
        try await withDirectory { directory in
            let journal = try FileChatTurnJournal(directory: directory, endpointScope: "scope")
            let pending = try turnRequest().pending
            try await journal.save(pending)
            let file = try #require(records(directory).first)
            let original = try String(contentsOf: file, encoding: .utf8)
            for bad in ["{", String(repeating: "x", count: 4097),
                        original.replacingOccurrences(of: "\"owner_id\":1", with: "\"owner_id\":2")]
            {
                try Data(bad.utf8).write(to: file)
                await #expect(throws: (any Error).self) { try await journal.read(ownerID: 1) }
                await #expect(throws: (any Error).self) { try await journal.save(pending) }
                #expect(try String(contentsOf: file, encoding: .utf8) == bad)
            }
        }
    }

    @Test
    func invalidDirectoryFailsWithoutSaving() async throws {
        try await withDirectory { directory in
            let file = directory.appendingPathComponent("file")
            try Data("file".utf8).write(to: file)
            let journal = try FileChatTurnJournal(directory: file, endpointScope: "scope")
            await #expect(throws: (any Error).self) { try await journal.save(turnRequest().pending) }
        }
    }

    private func withDirectory(_ body: (URL) async throws -> Void) async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        try await body(directory)
    }

    private func records(_ directory: URL) throws -> [URL] {
        let children = try FileManager.default.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil)
        return try children.flatMap { try FileManager.default.contentsOfDirectory(
            at: $0,
            includingPropertiesForKeys: nil
        ) }
        .filter { $0.pathExtension == "json" }
    }
}
