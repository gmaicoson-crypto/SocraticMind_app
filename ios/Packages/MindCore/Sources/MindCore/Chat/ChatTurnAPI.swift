import Foundation

/// Uses the transport's no-retry mutations and bounded history reads for authoritative text.
public struct ChatTurnAPI: ChatTurnGateway {
    private let transport: HTTPTransport
    private let history: ChatHistoryAPI

    public init(transport: HTTPTransport) {
        self.transport = transport
        history = ChatHistoryAPI(transport: transport)
    }

    public func stream(token: String, request: ChatTurnRequest,
                       onEvent: @Sendable (ChatEvent) async throws -> Void) async throws
    {
        try await transport.stream(path: "api/chat/stream", bearer: token, json: request.encoded(), onEvent: onEvent)
    }

    public func status(token: String, pending: PendingChatTurn) async throws -> RemoteChatTurn {
        let data = try await transport.request(
            method: "GET",
            path: "api/chat/requests/\(pending.requestID)",
            bearer: token
        )
        let value = try ChatFeedbackJSON.decode(StatusPayload.self, from: data)
        guard value.requestID == pending.requestID, value.sessionID == pending.target.sessionID else {
            throw ChatTurnFailure.invalidResponse
        }
        return RemoteChatTurn(
            status: value.status,
            ids: value.ids,
            feedback: value.feedback.value(status: value.status)
        )
    }

    public func cancel(token: String, pending: PendingChatTurn) async throws -> RemoteChatTurn {
        let json = try JSONSerialization.data(withJSONObject: [
            "session_id": pending.target.sessionID, "request_id": pending.requestID,
        ])
        let data = try await transport.request(method: "POST", path: "api/chat/cancel", bearer: token, json: json)
        let value = try ChatFeedbackJSON.decode(CancelPayload.self, from: data)
        guard value.status.terminal, value.ids != nil || value.status == .interrupted else {
            throw ChatTurnFailure.invalidResponse
        }
        return RemoteChatTurn(
            status: value.status,
            ids: value.ids,
            feedback: value.feedback.value(status: value.status)
        )
    }

    public func messages(token: String, pending: PendingChatTurn,
                         ids: ChatMessageIDs) async throws -> [StoredChatMessage]
    {
        let user = try await history.message(token: token, sessionID: pending.target.sessionID, id: ids.user)
        let ai = try await history.message(token: token, sessionID: pending.target.sessionID, id: ids.ai)
        guard user == nil || user?.role == "user", ai == nil || ai?.role == "ai" else {
            throw ChatTurnFailure.invalidResponse
        }
        let messages = [user, ai].compactMap(\.self)
        guard messages.allSatisfy({ $0.mode == pending.target.mode.rawValue && $0.nodeKey == pending.target.nodeKey })
        else {
            throw ChatTurnFailure.invalidResponse
        }
        return messages
    }
}

private struct StatusPayload: Decodable {
    let requestID: String
    let sessionID: String
    let status: ChatTurnStatus
    let ids: ChatMessageIDs
    let feedback: FeedbackPayload
    init(from decoder: any Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        requestID = try values.decode(String.self, forKey: .requestID)
        sessionID = try values.decode(String.self, forKey: .sessionID)
        status = try values.decode(ChatTurnStatus.self, forKey: .status)
        ids = try values.decode(ChatMessageIDs.self, forKey: .ids)
        feedback = try FeedbackPayload(from: decoder)
    }

    enum CodingKeys: String, CodingKey {
        case requestID = "request_id", sessionID = "session_id", status, ids = "msg_ids"
    }
}

private struct CancelPayload: Decodable {
    let status: ChatTurnStatus
    let ids: ChatMessageIDs?
    let feedback: FeedbackPayload
    init(from decoder: any Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        status = try values.decode(ChatTurnStatus.self, forKey: .status)
        ids = try values.decodeIfPresent(ChatMessageIDs.self, forKey: .ids)
        feedback = try FeedbackPayload(from: decoder)
    }

    enum CodingKeys: String, CodingKey { case status, ids = "msg_ids" }
}

private struct FeedbackPayload: Decodable {
    let usage: ChatJSONValue?
    let errorCode: String?
    enum CodingKeys: String, CodingKey { case usage, errorCode = "error_code", error }
    enum ErrorKeys: String, CodingKey { case code }

    init(from decoder: any Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        usage = ChatFeedbackJSON.usage(from: decoder)
        let nested = try? values.nestedContainer(keyedBy: ErrorKeys.self, forKey: .error)
        errorCode = (try? values.decode(String.self, forKey: .errorCode)) ?? (try? nested?.decode(
            String.self,
            forKey: .code
        ))
    }

    func value(status: ChatTurnStatus) -> ChatAnswerFeedback {
        ChatAnswerFeedback.decode([
            "usage": usage ?? .null, "error_code": errorCode.map(ChatJSONValue.string) ?? .null,
        ], status: status)
    }
}
