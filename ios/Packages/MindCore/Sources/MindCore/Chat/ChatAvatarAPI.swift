import Foundation

public protocol ChatAvatarGateway: Sendable {
    func upload(token: String, ownerID: Int64, sessionID: String, data: Data,
                format: AvatarImageFormat) async throws -> ChatAvatarResource
    func delete(token: String, sessionID: String) async throws -> Int64
    func image(_ resource: ChatAvatarResource) async throws -> Data
}

public struct ChatAvatarAPI: ChatAvatarGateway {
    private let transport: HTTPTransport
    public init(transport: HTTPTransport) {
        self.transport = transport
    }

    public func upload(token: String, ownerID: Int64, sessionID: String, data: Data,
                       format: AvatarImageFormat) async throws -> ChatAvatarResource
    {
        try validateHistorySession(sessionID)
        guard ownerID > 0, sessionID == sessionID.trimmingCharacters(in: .whitespacesAndNewlines)
        else { throw ChatAvatarFailure.invalidRequest }
        let upload = try MultipartUpload(fields: ["session_id": sessionID], fileField: "file",
                                         filename: "avatar." + format.rawValue, mimeType: format.mimeType, data: data)
        let response = try await transport.request(method: "POST", path: "api/chat/avatar", bearer: token,
                                                   multipart: upload)
        struct Response: Decodable { let avatar_url: ChatAvatarResource }
        let resource = try JSONDecoder().decode(Response.self, from: response).avatar_url
        guard resource.uploaded, try resource.belongsTo(ownerID: ownerID, sessionID: sessionID)
        else { throw ChatAvatarFailure.invalidResource }
        return resource
    }

    public func delete(token: String, sessionID: String) async throws -> Int64 {
        try validateHistorySession(sessionID)
        guard sessionID == sessionID.trimmingCharacters(in: .whitespacesAndNewlines)
        else { throw ChatAvatarFailure.invalidRequest }
        let body = try JSONEncoder().encode(["session_id": sessionID])
        let response = try await transport.request(method: "DELETE", path: "api/chat/avatar", bearer: token, json: body)
        struct Response: Decodable { let deleted: Int64 }
        let count = try JSONDecoder().decode(Response.self, from: response).deleted
        guard count >= 0 else { throw ChatAvatarFailure.invalidResource }
        return count
    }

    public func image(_ resource: ChatAvatarResource) async throws -> Data {
        try await transport.resource(path: resource.path, mimeTypes: Set(AvatarImageFormat.allCases.map(\.mimeType)),
                                     maximumBytes: ChatAvatarResource.maximumImageBytes)
    }
}
