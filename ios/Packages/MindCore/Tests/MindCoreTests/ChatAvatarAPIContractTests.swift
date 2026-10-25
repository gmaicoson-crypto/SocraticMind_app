import Foundation
@testable import MindCore
import Testing

struct ChatAvatarAPIContractTests {
    @Test
    func multipartPreservesUnicodeAndBinaryThenReadsAndDeletesOwnedResource() async throws {
        let server = try LoopbackFixture(); defer { server.close() }
        let transport = try HTTPTransport(endpoint: server.endpoint); defer { transport.close() }
        let api = ChatAvatarAPI(transport: transport), data = try avatarFixture()
        let result = try await api.upload(token: "avatar-valid", ownerID: 7, sessionID: data.session_id,
                                          data: data.image, format: .png)
        #expect(result.path == data.upload_url)
        var mutableBytes = data.image, mutableFields = ["session_id": data.session_id]
        let snapshot = try MultipartUpload(fields: mutableFields, fileField: "file", filename: "avatar.png",
                                           mimeType: "image/png", data: mutableBytes)
        mutableBytes.removeAll(); mutableFields["session_id"] = "changed"
        let response = try await transport.request(method: "POST", path: "api/chat/avatar", bearer: "avatar-valid",
                                                   multipart: snapshot)
        #expect(try JSONDecoder().decode([String: String].self, from: response)["avatar_url"] == result.path)
        #expect(try await api.image(result) == data.image)
        #expect(try await api.image(.fallback(for: .normal)) == data.image)
        #expect(try await api.delete(token: "avatar-valid", sessionID: data.session_id) == 1)
        #expect(try await api.delete(token: "avatar-empty", sessionID: data.session_id) == 0)
        for mode in [ChatMode.normal, .socratic] {
            #expect(ChatAvatarResource.presets(for: mode) == data.presets[mode.rawValue])
        }
    }

    @Test
    func rejectsExternalPathsWrongOwnersSessionsAndMalformedDeletion() async throws {
        let server = try LoopbackFixture(); defer { server.close() }
        let transport = try HTTPTransport(endpoint: server.endpoint); defer { transport.close() }
        let api = ChatAvatarAPI(transport: transport), data = try avatarFixture()
        for token in ["avatar-wrong-owner", "avatar-wrong-session", "avatar-preset", "avatar-external"] {
            await #expect(throws: (any Error).self) {
                try await api.upload(
                    token: token,
                    ownerID: 7,
                    sessionID: data.session_id,
                    data: data.image,
                    format: .png
                )
            }
        }
        for token in ["avatar-negative", "avatar-bool"] {
            await #expect(throws: (any Error).self) { try await api.delete(token: token, sessionID: data.session_id) }
        }
        for path in data.invalid_paths {
            #expect(throws: ChatAvatarFailure.self) { try ChatAvatarResource(path) }
        }
    }

    @Test
    func limitsAndMultipartHeaderSyntaxFailBeforeNetworkUse() async throws {
        let server = try LoopbackFixture(); defer { server.close() }
        let transport = try HTTPTransport(endpoint: server.endpoint); defer { transport.close() }
        let api = ChatAvatarAPI(transport: transport), data = try avatarFixture()
        for bytes in [Data(), Data(repeating: 0, count: 5 * 1024 * 1024 + 1)] {
            await #expect(throws: (any Error).self) {
                try await api.upload(
                    token: "avatar-valid",
                    ownerID: 7,
                    sessionID: data.session_id,
                    data: bytes,
                    format: .png
                )
            }
        }
        for id in [" ", " x ", String(repeating: "🙂", count: 101)] {
            await #expect(throws: (any Error).self) {
                try await api.upload(token: "avatar-valid", ownerID: 7, sessionID: id, data: data.image, format: .png)
            }
        }
        for name in ["bad\r\nheader", "\"name", "../file"] {
            #expect(throws: TransportFailure.self) { try MultipartUpload(
                fields: [:],
                fileField: "file",
                filename: name,
                mimeType: "image/png",
                data: data.image
            ) }
        }
        #expect(throws: TransportFailure.self) { try MultipartUpload(
            fields: ["file": "x"],
            fileField: "file",
            filename: "a.png",
            mimeType: "image/png",
            data: data.image
        ) }
        #expect(throws: TransportFailure.self) { try MultipartUpload(
            fields: [:],
            fileField: "file",
            filename: "a.png",
            mimeType: "image/png\r\nx: y",
            data: data.image
        ) }
        let upload = try MultipartUpload(fields: [:], fileField: "file", filename: "a.png",
                                         mimeType: "image/png", data: data.image)
        await #expect(throws: TransportFailure.self) {
            try await transport.request(method: "GET", path: "health", multipart: upload)
        }
        await #expect(throws: TransportFailure.self) {
            try await transport.request(method: "POST", path: "health", form: ["x": "y"], multipart: upload)
        }
    }

    @Test
    func authorizationRateLimitsAndServerFailuresRemainVisible() async throws {
        let server = try LoopbackFixture(); defer { server.close() }
        let transport = try HTTPTransport(endpoint: server.endpoint); defer { transport.close() }
        let api = ChatAvatarAPI(transport: transport), data = try avatarFixture()
        for (token, code) in [("expired", 401), ("avatar-rate", 429), ("avatar-server", 503)] {
            do {
                _ = try await api.upload(
                    token: token,
                    ownerID: 7,
                    sessionID: data.session_id,
                    data: data.image,
                    format: .png
                )
                Issue.record("Expected upload failure")
            } catch let error as HTTPFailure { #expect(error.status == code) }
            do {
                _ = try await api.delete(token: token, sessionID: data.session_id); Issue
                    .record("Expected delete failure")
            } catch let error as HTTPFailure { #expect(error.status == code) }
        }
    }

    @Test
    func resourcesRejectMIMEEmptyBodyOversizedLengthAndRedirects() async throws {
        let server = try LoopbackFixture(); defer { server.close() }
        let transport = try HTTPTransport(endpoint: server.endpoint); defer { transport.close() }
        let api = ChatAvatarAPI(transport: transport), paths = ChatAvatarResource.presets(for: .normal)
        for path in paths[1 ... 4] {
            await #expect(throws: (any Error).self) { try await api.image(ChatAvatarResource(path)) }
        }
        do {
            _ = try await api.image(ChatAvatarResource(paths[3])); Issue.record("Expected redirect refusal")
        } catch let error as HTTPFailure { #expect(error.status == 302) }
        await #expect(throws: TransportFailure.self) {
            try await transport.resource(path: paths[5], mimeTypes: ["image/png"], maximumBytes: 65)
        }
    }

    @Test
    func ambiguousUploadIsNotReplayedAndCanceledReadReleasesConnection() async throws {
        let server = try LoopbackFixture(); defer { server.close() }
        let transport = try HTTPTransport(endpoint: server.endpoint); defer { transport.close() }
        let api = ChatAvatarAPI(transport: transport), data = try avatarFixture()
        await #expect(throws: (any Error).self) {
            try await api.upload(token: "avatar-disconnect", ownerID: 7, sessionID: data.session_id,
                                 data: data.image, format: .png)
        }
        #expect(try await stats(transport, id: "avatar-disconnect").count == 1)
        let task = Task { try await api.image(ChatAvatarResource(ChatAvatarResource.presets(for: .normal)[5])) }
        try await waitResource(transport, closed: false)
        task.cancel(); await #expect(throws: (any Error).self) { try await task.value }
        try await waitResource(transport, closed: true)
    }

    private struct Stats: Decodable { let count: Int; let closed: Bool }
    private func stats(_ transport: HTTPTransport, id: String) async throws -> Stats {
        try await JSONDecoder().decode(
            Stats.self,
            from: transport.request(method: "GET", path: "stats", query: ["id": id])
        )
    }

    private func waitResource(_ transport: HTTPTransport, closed: Bool) async throws {
        let deadline = ContinuousClock.now.advanced(by: .seconds(3))
        while true {
            let value = try await stats(transport, id: "avatar-resource")
            if value.count == 1, value.closed == closed {
                return
            }
            guard ContinuousClock.now < deadline else { throw SessionTestError.timeout }
            try await Task.sleep(for: .milliseconds(10))
        }
    }
}
