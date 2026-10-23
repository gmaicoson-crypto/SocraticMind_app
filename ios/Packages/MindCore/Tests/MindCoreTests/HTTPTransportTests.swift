import Foundation
import MindCore
import Testing

struct HTTPTransportTests {
    private let token = "contract-token"

    @Test
    func credentialScopeIncludesSchemePortAndPrefix() throws {
        let base = try APIEndpoint("https://api.example.test/").credentialScope
        #expect(try base == APIEndpoint("HTTPS://API.EXAMPLE.TEST:443/").credentialScope)
        #expect(try base == APIEndpoint("https://api.example.test").credentialScope)
        for address in ["https://api.example.test:444/", "https://api.example.test/mobile/"] {
            #expect(try base != APIEndpoint(address).credentialScope)
        }
        #expect(try base != APIEndpoint("http://api.example.test/", developmentHTTPHosts: ["api.example.test"])
            .credentialScope)
    }

    @Test
    func jsonAndFormRoundTripWithoutDamagingUnicodeOrPlus() async throws {
        let fixture = try LoopbackFixture()
        defer { fixture.close() }
        let transport = try HTTPTransport(endpoint: fixture.endpoint)
        defer { transport.close() }
        let echo = try await transport.request(method: "POST", path: "echo-json", bearer: token,
                                               json: payload(["text": "中文🙂 + &"]))
        #expect(try decode(echo).text == "中文🙂 + &")
        let form = try await transport.request(method: "POST", path: "echo-form",
                                               form: ["username": "邮箱+test@example.test", "password": "p+& =中文"])
        #expect(try decode(form).valid == true)
        let health = try await transport.request(method: "GET", path: "health")
        #expect(try decode(health).status == "ok")
    }

    @Test
    func providerStreamsPreserveTerminalState() async throws {
        let fixture = try LoopbackFixture()
        defer { fixture.close() }
        let transport = try HTTPTransport(endpoint: fixture.endpoint)
        defer { transport.close() }
        for (name, status) in [("complete-utf8", "complete"), ("interrupted-partial", "interrupted")] {
            let recorder = EventRecorder()
            try await transport.stream(path: "stream", bearer: token, json: stream(name)) { await recorder.append($0) }
            let events = await recorder.snapshot()
            #expect(events.contains(.messageIDs(user: 1, ai: 2)))
            #expect(events.contains(.requestState(status)))
            #expect(events.last == .done)
            let text = events.compactMap { event -> String? in
                if case let .text(delta) = event {
                    return delta
                }; return nil
            }.joined()
            #expect(text == (status == "complete" ? "你好" : "部分"))
            let failures = events.filter {
                if case .failure = $0 {
                    return true
                }; return false
            }
            #expect(failures.isEmpty == (status == "complete"))
        }
    }

    @Test
    func firstEventArrivesBeforeTheServerFinishes() async throws {
        let fixture = try LoopbackFixture()
        defer { fixture.close() }
        let transport = try HTTPTransport(endpoint: fixture.endpoint)
        defer { transport.close() }
        let recorder = EventRecorder()
        try await transport.stream(path: "stream", bearer: token, json: stream("gated")) { event in
            await recorder.append(event)
            if case .text = event {
                _ = try await transport.request(method: "POST", path: "release", bearer: token,
                                                json: payload(["request_id": "gated"]))
            }
        }
        let events = await recorder.snapshot()
        #expect(events.first == .text("先到"))
        #expect(events.contains(.requestState("complete")))
    }

    @Test
    func abruptEofKeepsPartialTextAndNeverInventsSuccess() async throws {
        let fixture = try LoopbackFixture()
        defer { fixture.close() }
        let transport = try HTTPTransport(endpoint: fixture.endpoint)
        defer { transport.close() }
        let recorder = EventRecorder()
        await #expect(throws: TransportFailure.incompleteStream) {
            try await transport.stream(path: "stream", bearer: token, json: stream("truncated")) {
                await recorder.append($0)
            }
        }
        #expect(await recorder.snapshot() == [.text("部分")])
    }

    @Test
    func cancelledTaskClosesPendingReadWithoutReplay() async throws {
        let fixture = try LoopbackFixture()
        defer { fixture.close() }
        let transport = try HTTPTransport(endpoint: fixture.endpoint)
        defer { transport.close() }
        let recorder = EventRecorder()
        let task = Task {
            try await transport.stream(path: "stream", bearer: token, json: stream("cancel")) {
                await recorder.append($0)
            }
        }
        defer { task.cancel() }
        for _ in 0 ..< 100 {
            if await !(recorder.snapshot()).isEmpty {
                break
            }
            try await Task.sleep(for: .milliseconds(20))
        }
        #expect(await recorder.snapshot() == [.text("部分")])
        let cancelledAt = ContinuousClock.now
        task.cancel()
        let result = await task.result
        if case .success = result {
            Issue.record("Cancelled stream must not succeed")
        }
        #expect(cancelledAt.duration(to: .now) < .seconds(2))
        var closed = false
        for _ in 0 ..< 100 {
            let stats = try await decode(transport.request(method: "GET", path: "stats", query: ["id": "cancel"]))
            #expect(stats.count == 1)
            if stats.closed == true {
                closed = true; break
            }
            try await Task.sleep(for: .milliseconds(20))
        }
        #expect(closed)
    }

    @Test
    func httpErrorsAndRedirectsRemainVisible() async throws {
        let fixture = try LoopbackFixture()
        defer { fixture.close() }
        let transport = try HTTPTransport(endpoint: fixture.endpoint)
        defer { transport.close() }
        for (path, bearer, expected) in [("fail", token, 409), ("echo-json", "expired", 401), (
            "redirect",
            token,
            302
        ), ("invalid-form", token, 422)] {
            do {
                _ = try await transport.request(method: "POST", path: path, bearer: bearer,
                                                json: payload(["text": "ignored"]))
                Issue.record("HTTP \(expected) must fail")
            } catch let error as HTTPFailure {
                #expect(error.status == expected)
                if expected == 409 {
                    #expect(error.code == "VERSION_CONFLICT")
                    #expect(error.userMessage == "版本已更新")
                    #expect(error.retryable == false)
                }
                if expected == 401 {
                    #expect(error.userMessage == "登录已失效")
                }
                if expected == 422 {
                    #expect(error.userMessage == "密码至少 8 位")
                }
            }
        }
    }

    @Test
    func responseLimitsAndStreamMimeAreEnforced() async throws {
        let fixture = try LoopbackFixture()
        defer { fixture.close() }
        let transport = try HTTPTransport(endpoint: fixture.endpoint, maximumResponseBytes: 128)
        defer { transport.close() }
        await #expect(throws: TransportFailure.responseTooLarge) {
            _ = try await transport.request(method: "POST", path: "oversized", bearer: token, json: payload([:]))
        }
        await #expect(throws: TransportFailure.expectedSSE) {
            try await transport.stream(path: "stream", bearer: token, json: stream("wrong-type")) { _ in }
        }
    }

    @Test
    func endpointKeepsBasePathAndEscapesQuery() throws {
        let endpoint = try APIEndpoint("https://example.test/mobile/")
        let url = try endpoint.url(path: "/chat", query: ["id": "中文+a&b"])
        #expect(url.path == "/mobile/chat")
        #expect(URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems?.first?.value == "中文+a&b")
        #expect(url.absoluteString.contains("%2B"))
        #expect(throws: TransportFailure.invalidEndpoint) { try APIEndpoint("http://example.test/") }
        #expect(throws: TransportFailure.invalidEndpoint) { try APIEndpoint("https://token@example.test/") }
        for path in ["../chat", "//other.test/x", "chat?token=x", "%2e%2e/chat", "chat\\x", ""] {
            #expect(throws: TransportFailure.invalidPath) { try endpoint.url(path: path) }
        }
    }

    private func payload(_ values: [String: String]) throws -> Data {
        try JSONEncoder().encode(values)
    }

    private func stream(_ name: String) throws -> Data {
        try payload(["case": name, "request_id": name])
    }

    private func decode(_ data: Data) throws -> Reply {
        try JSONDecoder().decode(Reply.self, from: data)
    }

    private struct Reply: Decodable {
        let text: String?
        let status: String?
        let valid: Bool?
        let count: Int?
        let closed: Bool?
    }
}
