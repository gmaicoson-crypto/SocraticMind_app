import Foundation

public enum ChatEvent: Equatable, Sendable {
    case text(String)
    case messageIDs(user: Int64, ai: Int64)
    case requestState(String)
    case failure(code: String, message: String, retryable: Bool)
    case extensionPayload(String)
    case done
}

public enum ChatEventDecoder {
    public enum Failure: Error { case invalidPayload, invalidMessageID }

    public static func decode(_ data: String) throws -> [ChatEvent] {
        if data == "[DONE]" {
            return [.done]
        }
        guard let bytes = data.data(using: .utf8) else { throw Failure.invalidPayload }
        let payload = try JSONDecoder().decode(Payload.self, from: bytes)
        var events: [ChatEvent] = []
        if let ids = payload.msg_ids {
            guard ids.user > 0, ids.ai > 0 else { throw Failure.invalidMessageID }
            events.append(.messageIDs(user: ids.user, ai: ids.ai))
        }
        if let text = payload.text {
            events.append(.text(text))
        }
        if let state = payload.request_state {
            events.append(.requestState(state.status))
        }
        if let error = payload.error {
            events.append(.failure(code: error.code, message: error.message, retryable: error.retryable))
        }
        if events.isEmpty || payload.type != nil {
            events.append(.extensionPayload(data))
        }
        return events
    }

    private struct Payload: Decodable {
        let msg_ids: MessageIDs?
        let text: String?
        let request_state: RequestState?
        let error: StreamError?
        let type: String?

        enum CodingKeys: String, CodingKey {
            case msg_ids, text, request_state, error, type
        }

        init(from decoder: any Decoder) throws {
            let container = try decoder.container(keyedBy: CodingKeys.self)
            func present<T: Decodable>(_ type: T.Type, _ key: CodingKeys) throws -> T? {
                try container.contains(key) ? container.decode(type, forKey: key) : nil
            }
            msg_ids = try present(MessageIDs.self, .msg_ids)
            text = try present(String.self, .text)
            request_state = try present(RequestState.self, .request_state)
            error = try present(StreamError.self, .error)
            type = try present(String.self, .type)
        }

        struct MessageIDs: Decodable { let user: Int64; let ai: Int64 }
        struct RequestState: Decodable { let status: String }
        struct StreamError: Decodable { let code: String; let message: String; let retryable: Bool }
    }
}
