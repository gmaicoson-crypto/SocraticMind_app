import Foundation

public enum SuggestionSource: String, Sendable { case ai, fallback, local }

public struct ChatSuggestions: Decodable, Sendable, Equatable {
    public let items: [String]
    public let source: SuggestionSource
    enum CodingKeys: String, CodingKey { case suggestions, source }

    public init(items: [String], source: SuggestionSource) throws {
        guard items.count <= 12, Set(items).count == items.count,
              items.allSatisfy({ !$0.isEmpty && $0 == $0.trimmingCharacters(in: .whitespacesAndNewlines)
                      && $0.unicodeScalars.count <= 5000 }),
              items.reduce(0, { $0 + $1.utf8.count }) <= 65536
        else { throw HistoryContractFailure.invalidPage }
        self.items = items; self.source = source
    }

    public init(from decoder: any Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        let source = try values.decode(String.self, forKey: .source)
        guard let origin = SuggestionSource(rawValue: source), origin != .local
        else { throw HistoryContractFailure.invalidPage }
        try self.init(items: values.decode([String].self, forKey: .suggestions), source: origin)
    }
}

public protocol ChatSuggestionsGateway: Sendable {
    func suggestions(token: String, target: ChatTarget, exclude: [String], model: String?) async throws
        -> ChatSuggestions
}

public struct ChatSuggestionsAPI: ChatSuggestionsGateway {
    private let transport: HTTPTransport
    public init(transport: HTTPTransport) {
        self.transport = transport
    }

    public func suggestions(token: String, target: ChatTarget, exclude: [String], model: String?) async throws
        -> ChatSuggestions
    {
        try validateModelID(model)
        guard exclude.count <= 24,
              exclude.allSatisfy({ !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                      && $0.unicodeScalars.count <= 5000 })
        else { throw ChatTurnFailure.invalidRequest }
        var query = ["mode": target.mode.rawValue, "session_id": target.sessionID]
        if target.mode == .socratic, target.topicID > 0 {
            guard target.nodeKey.unicodeScalars.count <= 100 else { throw ChatTurnFailure.invalidRequest }
            query["topic_id"] = String(target.topicID); query["node_key"] = target.nodeKey
        }
        if let model {
            query["model"] = model
        }
        var seen: Set<String> = []
        let excluded = exclude.map { String(String.UnicodeScalarView(
            $0.trimmingCharacters(in: .whitespacesAndNewlines).unicodeScalars.prefix(80)
        )) }
        .filter { seen.insert($0).inserted }
        let data = try await transport.request(method: "GET", path: "api/chat/suggestions", bearer: token,
                                               query: query, repeatedQuery: ["exclude": excluded])
        return try JSONDecoder().decode(ChatSuggestions.self, from: data)
    }
}
