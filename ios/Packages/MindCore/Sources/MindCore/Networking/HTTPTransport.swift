import Foundation

/// One app-scoped session. Awaiting each event provides backpressure without an unbounded queue.
public final class HTTPTransport: Sendable {
    private let endpoint: APIEndpoint
    private let session: URLSession
    private let maximumResponseBytes: Int
    private let idleTimeout: TimeInterval

    public init(
        endpoint: APIEndpoint,
        idleTimeout: TimeInterval = 90,
        maximumResponseBytes: Int = 1024 * 1024
    ) throws {
        guard idleTimeout > 0, maximumResponseBytes > 0 else { throw TransportFailure.invalidRequest }
        self.endpoint = endpoint
        self.maximumResponseBytes = maximumResponseBytes
        self.idleTimeout = idleTimeout
        let configuration = URLSessionConfiguration.ephemeral
        configuration.urlCache = nil
        configuration.httpCookieStorage = nil
        configuration.httpShouldSetCookies = false
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        configuration.timeoutIntervalForRequest = idleTimeout
        configuration.timeoutIntervalForResource = 300
        session = URLSession(configuration: configuration, delegate: NoRedirectDelegate(), delegateQueue: nil)
    }

    public func close() {
        session.invalidateAndCancel()
    }

    public func request(
        method: String,
        path: String,
        bearer: String? = nil,
        json: Data? = nil,
        form: [String: String]? = nil,
        query: [String: String] = [:]
    ) async throws -> Data {
        let request = try makeRequest(method: method, path: path, bearer: bearer, json: json, form: form,
                                      query: query, accept: "application/json")
        let (bytes, response) = try await session.bytes(for: request)
        defer { bytes.task.cancel() }
        guard let response = response as? HTTPURLResponse else { throw TransportFailure.invalidResponse }
        let data = try await readBounded(bytes)
        guard (200 ... 299).contains(response.statusCode) else {
            throw HTTPFailure.decode(status: response.statusCode, data: data)
        }
        guard data.isEmpty || response.mimeType == "application/json" else { throw TransportFailure.expectedJSON }
        return data
    }

    public func stream(
        path: String,
        bearer: String,
        json: Data,
        onEvent: @Sendable (ChatEvent) async throws -> Void
    ) async throws {
        let request = try makeRequest(method: "POST", path: path, bearer: bearer, json: json, form: nil,
                                      query: [:], accept: "text/event-stream")
        let (bytes, response) = try await session.bytes(for: request)
        defer { bytes.task.cancel() }
        guard let response = response as? HTTPURLResponse else { throw TransportFailure.invalidResponse }
        guard (200 ... 299).contains(response.statusCode) else {
            throw try await HTTPFailure.decode(status: response.statusCode, data: readBounded(bytes))
        }
        guard response.mimeType == "text/event-stream" else { throw TransportFailure.expectedSSE }
        var decoder = try SSEDecoder()
        defer { decoder.finish() }
        var chunk: [UInt8] = []
        chunk.reserveCapacity(4096)
        for try await byte in bytes {
            try Task.checkCancellation()
            chunk.append(byte)
            if byte == 10 || byte == 13 || chunk.count == 4096 {
                let payloads = try decoder.feed(chunk)
                chunk.removeAll(keepingCapacity: true)
                for payload in payloads {
                    for event in try ChatEventDecoder.decode(payload) {
                        try Task.checkCancellation()
                        try await onEvent(event)
                        if event == .done {
                            return
                        }
                    }
                }
            }
        }
        throw TransportFailure.incompleteStream
    }

    private func readBounded(_ bytes: URLSession.AsyncBytes) async throws -> Data {
        var data = Data()
        for try await byte in bytes {
            try Task.checkCancellation()
            guard data.count < maximumResponseBytes else { throw TransportFailure.responseTooLarge }
            data.append(byte)
        }
        return data
    }

    private func makeRequest(
        method: String, path: String, bearer: String?, json: Data?, form: [String: String]?,
        query: [String: String], accept: String
    ) throws -> URLRequest {
        guard ["GET", "POST", "PUT", "PATCH", "DELETE"].contains(method), json == nil || form == nil,
              method != "GET" || (json == nil && form == nil)
        else { throw TransportFailure.invalidRequest }
        var request = try URLRequest(url: endpoint.url(path: path, query: query))
        request.httpMethod = method
        request.timeoutInterval = accept == "text/event-stream" ? idleTimeout : 30
        request.setValue(accept, forHTTPHeaderField: "Accept")
        if let bearer {
            guard !bearer.isEmpty, !bearer.contains(where: { $0 == "\r" || $0 == "\n" }) else {
                throw TransportFailure.invalidRequest
            }
            request.setValue("Bearer \(bearer)", forHTTPHeaderField: "Authorization")
        }
        if let json {
            request.httpBody = json
            request.setValue("application/json; charset=utf-8", forHTTPHeaderField: "Content-Type")
        } else if let form {
            var components = URLComponents()
            components.queryItems = form.sorted(by: { $0.key < $1.key }).map { URLQueryItem(
                name: $0.key,
                value: $0.value
            ) }
            request.httpBody = components.percentEncodedQuery?.replacingOccurrences(of: "+", with: "%2B")
                .data(using: .utf8)
            request.setValue("application/x-www-form-urlencoded; charset=utf-8", forHTTPHeaderField: "Content-Type")
        }
        return request
    }
}

/// No mutable state; redirects must never silently replay a mutation or forward credentials.
private final class NoRedirectDelegate: NSObject, URLSessionTaskDelegate, Sendable {
    func urlSession(
        _: URLSession, task _: URLSessionTask, willPerformHTTPRedirection _: HTTPURLResponse,
        newRequest _: URLRequest, completionHandler: @escaping @Sendable (URLRequest?) -> Void
    ) {
        completionHandler(nil)
    }
}
