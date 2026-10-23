import Foundation
@testable import MindCore
import Testing

struct ChatHistoryAPIContractTests {
    @Test
    func readsBoundedPagesWithExactCursorAndOpaqueSessionQuery() async throws {
        let fixture = try loadFixture()
        let server = try LoopbackFixture()
        defer { server.close() }
        let transport = try HTTPTransport(endpoint: server.endpoint)
        defer { transport.close() }
        let api = ChatHistoryAPI(transport: transport)
        let sessions = try await api.conversations(token: "contract-token", limit: 1)
        #expect(sessions.snapshotID == 104)
        #expect(sessions.items.first?.sessionID == fixture.session_id)
        #expect(sessions.items.first?.title == "合成测试对话")
        let olderSessions = try await api.conversations(token: "contract-token", limit: 1, cursor: sessions.nextCursor)
        #expect(olderSessions.items.first?.sessionID == "older-session")
        #expect(olderSessions.items.first?.title == nil)
        #expect(olderSessions.nextCursor == nil)
        let first = try await api.messages(token: "contract-token", sessionID: fixture.session_id, limit: 2)
        #expect(first.items.map(\.id) == [104, 103])
        let expectedCursor = try HistoryCursor(snapshotID: 104, beforeID: 103)
        #expect(first.nextCursor == expectedCursor)
        #expect(first.items == fixture.messages_first.items)
        let older = try await api.messages(token: "contract-token", sessionID: fixture.session_id,
                                           limit: 2, cursor: first.nextCursor)
        #expect(older.items.map(\.id) == [102, 101])
        #expect(older.nextCursor == nil)
        #expect(older.snapshotID == 104)
        let empty = try await api.messages(token: "contract-token", sessionID: "empty", limit: 2)
        #expect(empty.snapshotID == 0)
        #expect(empty.nextCursor == nil)
        #expect(try await api.conversations(token: "contract-token", mode: .socratic, limit: 1).items.isEmpty)
    }

    @Test
    func rejectsMalformedOrMismatchedPagesFromSharedCases() async throws {
        let fixture = try loadFixture()
        let invalid = try JSONDecoder().decode(InvalidFixture.self, from: data("invalid-history-pages.json"))
        let server = try LoopbackFixture()
        defer { server.close() }
        let transport = try HTTPTransport(endpoint: server.endpoint)
        defer { transport.close() }
        let api = ChatHistoryAPI(transport: transport)
        for item in invalid.cases {
            let cursor = try item.cursor.map { try HistoryCursor(snapshotID: $0.snapshot_id, beforeID: $0.before_id) }
            do {
                if item.kind == "messages" {
                    _ = try await api.messages(token: "history-case-" + item.id, sessionID: fixture.session_id,
                                               limit: 2, cursor: cursor)
                } else {
                    _ = try await api.conversations(token: "history-case-" + item.id, limit: 2, cursor: cursor)
                }
                Issue.record("Accepted invalid page: \(item.id)")
            } catch is HistoryContractFailure {
                // Semantic mismatch is a contract failure, not successful empty history.
            } catch is DecodingError {
                // Wrong / missing JSON types are rejected before projection.
            }
        }
    }

    @Test
    func unauthorizedIsNotAnEmptyHistory() async throws {
        let fixture = try loadFixture()
        let server = try LoopbackFixture()
        defer { server.close() }
        let transport = try HTTPTransport(endpoint: server.endpoint)
        defer { transport.close() }
        do {
            _ = try await ChatHistoryAPI(transport: transport).messages(token: "expired", sessionID: fixture.session_id)
            Issue.record("Expired credentials must fail")
        } catch let failure as HTTPFailure {
            #expect(failure.status == 401)
        }
    }

    @Test
    func preservesUnknownStructuredFieldsAndExactIntegerIDs() throws {
        let fixture = try loadFixture()
        let message = try #require(fixture.messages_first.items.first)
        #expect(message.content.contains("中文🙂"))
        #expect(message.metadata?["future"] == .object([
            "flag": .bool(true), "count": .integer(2), "ratio": .decimal(0.5), "names": .array([.string("甲"), .null]),
        ]))
        let exact = try JSONDecoder().decode(ChatJSONValue.self, from: Data("9007199254740993".utf8))
        #expect(exact == .integer(9_007_199_254_740_993))
        #expect(throws: HistoryContractFailure.self) { try HistoryCursor(snapshotID: 1, beforeID: 2) }
        #expect(throws: HistoryContractFailure.self) { try HistoryCursor(snapshotID: 0, beforeID: 0) }
    }

    private func data(_ name: String) throws -> Data {
        var root = URL(fileURLWithPath: #filePath)
        for _ in 0 ..< 6 {
            root.deleteLastPathComponent()
        }
        return try Data(contentsOf: root.appendingPathComponent("contracts/fixtures/" + name))
    }

    private func loadFixture() throws -> Fixture {
        try JSONDecoder().decode(Fixture.self, from: data("chat-history.json"))
    }

    private struct Fixture: Decodable {
        let session_id: String
        let messages_first: HistoryPagePayload<StoredChatMessage>
    }

    private struct InvalidFixture: Decodable {
        let cases: [Case]
        struct Case: Decodable {
            let id: String
            let kind: String
            let cursor: Cursor?
        }

        struct Cursor: Decodable { let snapshot_id: Int64; let before_id: Int64 }
    }
}
