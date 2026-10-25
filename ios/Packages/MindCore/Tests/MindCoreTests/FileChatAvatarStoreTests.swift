import Foundation
@testable import MindCore
import Testing

struct FileChatAvatarStoreTests {
    private let preset = ChatAvatarResource.fallback(for: .normal)

    @Test
    func opaqueUnicodeIdentitiesRemainDistinctAndDuplicateRecordsAreRejected() async throws {
        try await withDirectory { root in
            let store = try FileChatAvatarStore(directory: root, endpointScope: "scope")
            let first = "caf\u{e9}", second = "cafe\u{301}", other = ChatAvatarResource.fallback(for: .socratic)
            #expect(first == second && !first.utf8.elementsEqual(second.utf8))
            try await store.replace(ownerID: 7, sessionID: first, expected: nil, value: preset)
            try await store.replace(ownerID: 7, sessionID: second, expected: nil, value: other)
            let reopened = try await FileChatAvatarStore(directory: root, endpointScope: "scope").read(ownerID: 7)
            #expect(reopened.count == 2 && reopened[first] == preset && reopened[second] == other)
            let file = try #require(records(root).first)
            var record = try #require(JSONSerialization.jsonObject(with: Data(contentsOf: file)) as? [String: Any])
            var choices = try #require(record["choices"] as? [[String: Any]])
            try choices.append(#require(choices.first)); record["choices"] = choices
            try JSONSerialization.data(withJSONObject: record).write(to: file)
            await #expect(throws: ChatAvatarFailure.self) { try await store.read(ownerID: 7) }
        }
    }

    @Test
    func reopenPreservesAccountEndpointAndJournalIsolationWithOnlyPathsOnDisk() async throws {
        try await withDirectory { root in
            let store = try FileChatAvatarStore(directory: root, endpointScope: "scope")
            let data = try avatarFixture(), resource = try ChatAvatarResource(data.upload_url)
            try await store.replace(ownerID: 7, sessionID: data.session_id, expected: nil, value: resource)
            try await store.replace(ownerID: 8, sessionID: "other", expected: nil, value: preset)
            let journal = try AccountFileStorage(directory: root, endpointScope: "scope", namespace: "chat-turns",
                                                 maximumBytes: 4096)
            let pending = Data("synthetic recovery identifiers".utf8)
            try journal.write(7, bytes: pending)
            #expect(try await FileChatAvatarStore(directory: root, endpointScope: "scope")
                .read(ownerID: 7)[data.session_id]
                == resource)
            #expect(try await store.read(ownerID: 8)["other"] == preset)
            #expect(try await FileChatAvatarStore(directory: root, endpointScope: "other-scope").read(ownerID: 7)
                .isEmpty)
            try await store.clear(ownerID: 7)
            #expect(try await store.read(ownerID: 7).isEmpty)
            #expect(try await store.read(ownerID: 8)["other"] == preset)
            #expect(try journal.read(7) == pending)
            for file in try records(root) {
                let text = try String(contentsOf: file, encoding: .utf8)
                #expect(!text.contains("access_token") && !text.contains("image_base64") && !text
                    .contains("user_input"))
            }
        }
    }

    @Test
    func staleReplacementOrRemovalCannotOverwriteNewerChoice() async throws {
        try await withDirectory { root in
            let store = try FileChatAvatarStore(directory: root, endpointScope: "scope")
            let next = try ChatAvatarResource(ChatAvatarResource.presets(for: .normal)[1])
            try await store.replace(ownerID: 7, sessionID: "main", expected: nil, value: preset)
            try await store.replace(ownerID: 7, sessionID: "main", expected: preset, value: next)
            for value in [nil, preset] {
                await #expect(throws: ChatAvatarFailure.self) {
                    try await store.replace(ownerID: 7, sessionID: "main", expected: preset, value: value)
                }
            }
            #expect(try await store.read(ownerID: 7)["main"] == next)
            try await store.replace(ownerID: 7, sessionID: "main", expected: next, value: nil)
            #expect(try await store.read(ownerID: 7).isEmpty)
        }
    }

    @Test
    func corruptOwnerSchemaPathAndOversizedRecordsFailWithoutOverwrite() async throws {
        try await withDirectory { root in
            let store = try FileChatAvatarStore(directory: root, endpointScope: "scope")
            try await store.replace(ownerID: 7, sessionID: "main", expected: nil, value: preset)
            let file = try #require(records(root).first), original = try String(contentsOf: file, encoding: .utf8)
            let badPath = try JSONSerialization.data(withJSONObject: ["schema": 1, "owner_id": 7,
                                                                      "choices": [[
                                                                          "session_id": "main",
                                                                          "path": "https://example.test/a",
                                                                      ]]])
            let invalid = [Data("{".utf8), Data(repeating: 120, count: 512 * 1024 + 1), badPath,
                           Data(original.replacingOccurrences(of: "\"schema\":1", with: "\"schema\":2").utf8),
                           Data(original.replacingOccurrences(of: "\"owner_id\":7", with: "\"owner_id\":8").utf8)]
            for bytes in invalid {
                try bytes.write(to: file)
                await #expect(throws: (any Error).self) { try await store.read(ownerID: 7) }
                await #expect(throws: (any Error).self) {
                    try await store.replace(ownerID: 7, sessionID: "main", expected: preset, value: nil)
                }
                #expect(try Data(contentsOf: file) == bytes)
            }
            try await store.clear(ownerID: 7); #expect(try await store.read(ownerID: 7).isEmpty)
        }
    }

    @Test
    func entryCapacityPreservesExistingChoicesAndAllowsReplacementAndRemoval() async throws {
        try await withDirectory { root in
            let store = try FileChatAvatarStore(directory: root, endpointScope: "scope")
            try await store.replace(ownerID: 7, sessionID: "seed", expected: nil, value: preset)
            let file = try #require(records(root).first)
            let choices = (0 ..< 1000).map { ["session_id": "session-\($0)", "path": preset.path] }
            let original = try JSONSerialization.data(withJSONObject: ["schema": 1, "owner_id": 7, "choices": choices])
            try original.write(to: file)
            await #expect(throws: ChatAvatarFailure.self) {
                try await store.replace(ownerID: 7, sessionID: "extra", expected: nil, value: preset)
            }
            #expect(try Data(contentsOf: file) == original)
            let next = ChatAvatarResource.fallback(for: .socratic)
            try await store.replace(ownerID: 7, sessionID: "session-0", expected: preset, value: next)
            #expect(try await store.read(ownerID: 7).count == 1000)
            try await store.replace(ownerID: 7, sessionID: "session-0", expected: next, value: nil)
            try await store.replace(ownerID: 7, sessionID: "extra", expected: nil, value: preset)
            #expect(try await store.read(ownerID: 7).count == 1000)
        }
    }

    @Test
    func atomicIOBudgetPreservesBytesAndInvalidDirectoryCannotSave() async throws {
        try await withDirectory { root in
            let io = try AccountFileStorage(
                directory: root,
                endpointScope: "scope",
                namespace: "chat-avatars",
                maximumBytes: 32
            )
            try io.write(7, bytes: Data("old".utf8))
            #expect(throws: (any Error).self) { try io.write(7, bytes: Data(repeating: 120, count: 33)) }
            #expect(try io.read(7) == Data("old".utf8))
            let blocked = root.appendingPathComponent("blocked")
            try Data("file".utf8).write(to: blocked)
            let store = try FileChatAvatarStore(directory: blocked, endpointScope: "scope")
            await #expect(throws: (any Error).self) {
                try await store.replace(ownerID: 7, sessionID: "main", expected: nil, value: preset)
            }
        }
    }

    @Test
    func concurrentComparisonAcceptsOneWriterAndRejectsForeignUploads() async throws {
        try await withDirectory { root in
            let store = try FileChatAvatarStore(directory: root, endpointScope: "scope")
            let other = ChatAvatarResource.fallback(for: .socratic)
            let successes = await withTaskGroup(of: Bool.self) { group in
                for value in [preset, other] {
                    group.addTask {
                        do { try await store.replace(
                            ownerID: 7,
                            sessionID: "main",
                            expected: nil,
                            value: value
                        ); return true } catch { return false }
                    }
                }
                var count = 0
                for await success in group {
                    if success {
                        count += 1
                    }
                }
                return count
            }
            #expect(successes == 1)
            let choices = try await store.read(ownerID: 7)
            let winner = try #require(choices["main"])
            #expect([preset, other].contains(winner))
            let data = try avatarFixture(), resource = try ChatAvatarResource(data.upload_url)
            for (owner, id) in [(Int64(7), "different-session"), (Int64(8), data.session_id)] {
                await #expect(throws: (any Error).self) {
                    try await store.replace(ownerID: owner, sessionID: id, expected: nil, value: resource)
                }
            }
            await #expect(throws: (any Error).self) {
                try await store.replace(ownerID: 7, sessionID: " space ", expected: nil, value: preset)
            }
        }
    }

    private func withDirectory(_ body: (URL) async throws -> Void) async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        try await body(root)
    }

    private func records(_ root: URL) throws -> [URL] {
        try FileManager.default.contentsOfDirectory(at: root, includingPropertiesForKeys: nil).flatMap {
            try FileManager.default.contentsOfDirectory(at: $0, includingPropertiesForKeys: nil)
        }.filter { $0.pathExtension == "json" }
    }
}
