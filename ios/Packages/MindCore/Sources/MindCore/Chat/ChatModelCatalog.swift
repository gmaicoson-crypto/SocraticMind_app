import Foundation

public enum ChatModelSource: String, Decodable, Sendable { case environment, custom }

/// Configuration identity is byte exact, even when two IDs are canonically equivalent Unicode strings.
public struct ChatModelOption: Decodable, Sendable, Equatable {
    public let id: String
    public let name: String
    public let model: String
    public let source: ChatModelSource
    public var identity: Data {
        Data(id.utf8)
    }

    enum CodingKeys: String, CodingKey { case id, name, model, source }

    public init(id: String, name: String, model: String, source: ChatModelSource) throws {
        try validateModelID(id)
        guard [name, model].allSatisfy({ !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty &&
                $0.unicodeScalars.count <= 200 }) else { throw HistoryContractFailure.invalidPage }
        self.id = id; self.name = name; self.model = model; self.source = source
    }

    public init(from decoder: any Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        try self.init(id: values.decode(String.self, forKey: .id), name: values.decode(String.self, forKey: .name),
                      model: values.decode(String.self, forKey: .model), source: values.decode(
                          ChatModelSource.self,
                          forKey: .source
                      ))
    }

    public static func == (lhs: Self, rhs: Self) -> Bool {
        lhs.identity == rhs.identity && lhs.name == rhs.name && lhs.model == rhs.model && lhs.source == rhs.source
    }
}

public struct ChatModelCatalog: Decodable, Sendable {
    public let models: [ChatModelOption]
    enum CodingKeys: String, CodingKey { case models }

    public init(models: [ChatModelOption]) throws {
        guard models.count <= 256, Set(models.map(\.identity)).count == models.count,
              models.reduce(0, { $0 + $1.id.utf8.count + $1.name.utf8.count + $1.model.utf8.count }) <= 256 * 1024
        else { throw HistoryContractFailure.invalidPage }
        self.models = models
    }

    public init(from decoder: any Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        try self.init(models: values.decode([ChatModelOption].self, forKey: .models))
    }
}

func validateModelID(_ value: String?) throws {
    guard let value else { return }
    guard !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, value.unicodeScalars.count <= 100
    else { throw ChatTurnFailure.invalidRequest }
}

public protocol ChatModelGateway: Sendable {
    func catalog(token: String) async throws -> ChatModelCatalog
}

public struct ChatModelAPI: ChatModelGateway {
    private let transport: HTTPTransport
    public init(transport: HTTPTransport) {
        self.transport = transport
    }

    public func catalog(token: String) async throws -> ChatModelCatalog {
        let data = try await transport.request(method: "GET", path: "api/llm/models", bearer: token)
        return try JSONDecoder().decode(ChatModelCatalog.self, from: data)
    }
}

public struct ChatModelState: Sendable {
    public internal(set) var account: HistoryAccount?
    public internal(set) var catalog: ChatModelCatalog?
    public internal(set) var selected: ChatModelOption?
    public internal(set) var loading = false
    public internal(set) var notice: String?
    public var selectedID: String? {
        selected?.id
    }

    public var label: String {
        selected?.name ?? "服务端默认"
    }

    public var available: Bool {
        selected == nil || catalog?.models.contains(where: { $0.identity == selected?.identity }) == true
    }
}
