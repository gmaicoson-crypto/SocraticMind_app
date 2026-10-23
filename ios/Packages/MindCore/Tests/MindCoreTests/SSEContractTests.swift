import Foundation
import MindCore
import Testing

struct SSEContractTests {
    @Test
    func framingAtEveryBoundary() throws {
        let fixture: FramingFixture = try load("sse-framing.json")
        for item in fixture.cases {
            try forEveryPartition(item.wire) { chunks in
                var decoder = try SSEDecoder()
                let events = try chunks.flatMap { try decoder.feed($0) }
                decoder.finish()
                #expect(events == item.payloads, Comment(rawValue: item.id))
            }
        }
    }

    @Test
    func providerFramesAtEveryBoundary() throws {
        let fixture: ChatFixture = try load("chat-streams.json")
        for item in fixture.cases {
            try forEveryPartition(item.wire) { chunks in
                var decoder = try SSEDecoder()
                let payloads = try chunks.flatMap { try decoder.feed($0) }
                let events = try payloads.flatMap { try ChatEventDecoder.decode($0) }
                decoder.finish()
                let text = events.compactMap { event -> String? in
                    if case let .text(delta) = event {
                        return delta
                    }
                    return nil
                }.joined()
                #expect(text == item.text)
                #expect(events.contains(.messageIDs(user: 1, ai: 2)))
                #expect(events.contains(.requestState(item.status)))
                #expect(events.last == .done)
                let failures = events.filter {
                    if case .failure = $0 {
                        return true
                    }; return false
                }
                if item.status == "interrupted" {
                    #expect(failures == [.failure(code: "AI_STREAM_INCOMPLETE", message: "测试流中断", retryable: true)])
                } else {
                    #expect(failures.isEmpty)
                }
            }
        }
    }

    @Test
    func rejectMalformedChatEvents() throws {
        let fixture: InvalidFixture = try load("invalid-chat-events.json")
        for payload in fixture.payloads {
            #expect(throws: (any Error).self) { try ChatEventDecoder.decode(payload) }
        }
    }

    @Test
    func malformedUTF8ClosesParser() throws {
        var decoder = try SSEDecoder()
        #expect(throws: SSEDecoder.Failure.invalidUTF8) { try decoder.feed([0xC3, 10]) }
        #expect(throws: SSEDecoder.Failure.closed) { try decoder.feed([UInt8]()) }
    }

    @Test
    func lineAndEventLimitsAreIndependent() throws {
        var atLimit = try SSEDecoder(maxLineBytes: 7, maxEventBytes: 7)
        #expect(try atLimit.feed(Array("data: a\n\n".utf8)) == ["a"])
        var longLine = try SSEDecoder(maxLineBytes: 7)
        #expect(throws: SSEDecoder.Failure.lineTooLarge) { try longLine.feed(Array("data: ab".utf8)) }
        var longEvent = try SSEDecoder(maxLineBytes: 7, maxEventBytes: 13)
        #expect(throws: SSEDecoder.Failure.eventTooLarge) {
            try longEvent.feed(Array("data: a\ndata: b\n".utf8))
        }
        #expect(throws: SSEDecoder.Failure.closed) { try longEvent.feed([UInt8]()) }
    }

    @Test
    func doneAndUnknownStateDoNotInventSuccess() throws {
        #expect(try ChatEventDecoder.decode("[DONE]") == [.done])
        #expect(try ChatEventDecoder
            .decode(#"{"request_state":{"status":"future-state"}}"#) == [.requestState("future-state")])
        let unknown = #"{"type":"future-event","extra":1}"#
        #expect(try ChatEventDecoder.decode(unknown) == [.extensionPayload(unknown)])
    }

    @Test
    func endOfFileDiscardsIncompleteEventAndClosesParser() throws {
        var decoder = try SSEDecoder()
        #expect(try decoder.feed(Array("data: pending\n".utf8)).isEmpty)
        decoder.finish()
        #expect(throws: SSEDecoder.Failure.closed) { try decoder.feed([10]) }
    }

    private func forEveryPartition(_ wire: String, check: ([[UInt8]]) throws -> Void) throws {
        let bytes = Array(wire.utf8)
        for cut in 0 ... bytes.count {
            try check([Array(bytes[..<cut]), Array(bytes[cut...])])
        }
        try check(bytes.map { [$0] })
    }

    private func load<T: Decodable>(_ name: String) throws -> T {
        var root = URL(fileURLWithPath: #filePath)
        for _ in 0 ..< 6 {
            root.deleteLastPathComponent()
        }
        let url = root.appendingPathComponent("contracts/fixtures").appendingPathComponent(name)
        return try JSONDecoder().decode(T.self, from: Data(contentsOf: url))
    }

    private struct FramingFixture: Decodable {
        let cases: [Item]
        struct Item: Decodable { let id: String; let wire: String; let payloads: [String] }
    }

    private struct ChatFixture: Decodable {
        let cases: [Item]
        struct Item: Decodable { let id: String; let wire: String; let text: String; let status: String }
    }

    private struct InvalidFixture: Decodable { let payloads: [String] }
}
