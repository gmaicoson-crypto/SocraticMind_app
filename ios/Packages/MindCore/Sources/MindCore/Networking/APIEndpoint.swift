import Foundation

public struct APIEndpoint: Sendable {
    private let base: URL
    public var credentialScope: String {
        base.absoluteString
    }

    public init(_ address: String, developmentHTTPHosts: Set<String> = []) throws {
        guard var components = URLComponents(string: address), let host = components.host?.lowercased(),
              let scheme = components.scheme?.lowercased(),
              scheme == "https" || (scheme == "http" && developmentHTTPHosts.contains(host)),
              let url = components.url,
              url.user == nil, url.password == nil, url.query == nil, url.fragment == nil,
              url.path.isEmpty || url.hasDirectoryPath
        else { throw TransportFailure.invalidEndpoint }
        components.scheme = scheme
        components.host = host
        if components.port == (scheme == "https" ? 443 : 80) {
            components.port = nil
        }
        if components.percentEncodedPath.isEmpty {
            components.percentEncodedPath = "/"
        }
        guard let normalized = components.url else { throw TransportFailure.invalidEndpoint }
        base = normalized
    }

    public func url(path: String, query: [String: String] = [:],
                    repeatedQuery: [String: [String]] = [:]) throws -> URL
    {
        guard Set(query.keys).isDisjoint(with: repeatedQuery.keys) else { throw TransportFailure.invalidRequest }
        let relative = path.hasPrefix("/") ? String(path.dropFirst()) : path
        let parts = relative.split(separator: "/", omittingEmptySubsequences: false)
        guard parts.allSatisfy({ !$0.isEmpty && $0 != "." && $0 != ".." }),
              !path.contains(where: { "?#\\%".contains($0) })
        else { throw TransportFailure.invalidPath }
        var result = base
        for part in parts {
            result.appendPathComponent(String(part))
        }
        guard var components = URLComponents(url: result, resolvingAgainstBaseURL: false) else {
            throw TransportFailure.invalidEndpoint
        }
        if !query.isEmpty || !repeatedQuery.isEmpty {
            components.queryItems = query.sorted(by: { $0.key < $1.key }).map { URLQueryItem(
                name: $0.key,
                value: $0.value
            ) } + repeatedQuery.sorted(by: { $0.key < $1.key }).flatMap { name, values in
                values.map { URLQueryItem(name: name, value: $0) }
            }
        }
        components.percentEncodedQuery = components.percentEncodedQuery?.replacingOccurrences(of: "+", with: "%2B")
        guard let url = components.url else { throw TransportFailure.invalidEndpoint }
        return url
    }
}
