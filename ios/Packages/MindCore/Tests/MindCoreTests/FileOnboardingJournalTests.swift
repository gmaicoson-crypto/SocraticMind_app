import Foundation
@testable import MindCore
import Testing

struct FileOnboardingJournalTests {
    @Test
    func reopenRetainsOnlyStableIdentifiersIsolatedByBackendAndOwner() async throws {
        try await directory { root in
            let first = try PendingOnboarding(ownerID: 1, runID: .create(), confirmationID: .create())
            let second = try PendingOnboarding(ownerID: 2, runID: .create(), confirmationID: .create())
            let journal = try FileOnboardingJournal(directory: root, endpointScope: "scope")
            try await journal.save(first); try await journal.save(second)
            #expect(try await FileOnboardingJournal(directory: root, endpointScope: "scope").read(ownerID: 1) == first)
            #expect(try await FileOnboardingJournal(directory: root, endpointScope: "other").read(ownerID: 1) == nil)
            let file = try #require(records(root).first)
            let row = try LearningRow(JSONSerialization.jsonObject(with: Data(contentsOf: file)))
            #expect(Set(row.values.keys) == ["schema", "owner_id", "run_id", "confirmation_id"])
            try await journal.clear(first)
            #expect(try await journal.read(ownerID: 1) == nil); #expect(try await journal.read(ownerID: 2) == second)
        }
    }

    @Test
    func staleSaveAndClearCannotReplaceAnotherPendingRecord() async throws {
        try await directory { root in
            let journal = try FileOnboardingJournal(directory: root, endpointScope: "scope")
            let first = try PendingOnboarding(ownerID: 1, runID: .create(), confirmationID: .create())
            let other = try PendingOnboarding(ownerID: 1, runID: first.runID, confirmationID: .create())
            try await journal.save(first); try await journal.save(first)
            await #expect(throws: OnboardingJournalFailure.self) { try await journal.save(other) }
            await #expect(throws: OnboardingJournalFailure.self) { try await journal.clear(other) }
            #expect(try await journal.read(ownerID: 1) == first)
        }
    }

    @Test
    func corruptNumericSchemaOversizedAndMismatchedRecordsAreNotOverwritten() async throws {
        try await directory { root in
            let journal = try FileOnboardingJournal(directory: root, endpointScope: "scope")
            let pending = try PendingOnboarding(ownerID: 1, runID: .create(), confirmationID: .create())
            try await journal.save(pending)
            let file = try #require(records(root).first), original = try String(contentsOf: file, encoding: .utf8)
            var bad = [
                "{",
                "",
                String(repeating: "x", count: 4097),
                original.replacingOccurrences(of: "\"schema\":1", with: "\"schema\":1.0"),
                original.replacingOccurrences(of: "\"owner_id\":1", with: "\"owner_id\":2"),
                original.replacingOccurrences(of: pending.runID.value, with: "../"),
            ].map { Data($0.utf8) }
            bad.append(Data([255]))
            for bytes in bad {
                try bytes.write(to: file)
                await #expect(throws: (any Error).self) { try await journal.read(ownerID: 1) }
                await #expect(throws: (any Error).self) { try await journal.save(pending) }
                await #expect(throws: (any Error).self) { try await journal.clear(pending) }
                #expect(try Data(contentsOf: file) == bytes)
            }
        }
    }

    @Test
    func unwritableDirectoryNeverClaimsSuccessfulSave() async throws {
        try await directory { root in
            let file = root.appendingPathComponent("file"); try Data("file".utf8).write(to: file)
            let journal = try FileOnboardingJournal(directory: file, endpointScope: "scope")
            let pending = try PendingOnboarding(ownerID: 1, runID: .create(), confirmationID: .create())
            await #expect(throws: (any Error).self) { try await journal.save(pending) }
        }
    }

    private func directory(_ body: (URL) async throws -> Void) async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        try await body(root)
    }

    private func records(_ root: URL) throws -> [URL] {
        let children = try FileManager.default.contentsOfDirectory(at: root, includingPropertiesForKeys: nil)
        return try children.flatMap { try FileManager.default.contentsOfDirectory(
            at: $0,
            includingPropertiesForKeys: nil
        ) }.filter { $0.pathExtension == "json" }
    }
}
