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
        query: [String: String] = [:],
        repeatedQuery: [String: [String]] = [:],
        multipart: MultipartUpload? = nil
    ) async throws -> Data {
        let request = try makeRequest(method: method, path: path, bearer: bearer, json: json, form: form,
                                      query: query, accept: "application/json", repeatedQuery: repeatedQuery,
                                      multipart: multipart)
        let (data, response) = try await receive(request, maximumBytes: maximumResponseBytes)
        guard data.isEmpty || response.mimeType == "application/json" else { throw TransportFailure.expectedJSON }
        return data
    }

    /// Same-endpoint public resources; never attach credentials or follow redirects.
    public func resource(path: String, mimeTypes: Set<String>, maximumBytes: Int) async throws -> Data {
        guard (1 ... 5 * 1024 * 1024).contains(maximumBytes), !mimeTypes.isEmpty,
              mimeTypes.allSatisfy({ $0.range(of: "^[a-z0-9.+_-]+/[a-z0-9.+_-]+$", options: .regularExpression)
                      == $0.startIndex ..< $0.endIndex }) else { throw TransportFailure.invalidRequest }
        let request = try makeRequest(method: "GET", path: path, bearer: nil, json: nil, form: nil,
                                      query: [:], accept: mimeTypes.sorted().joined(separator: ", "))
        let (data, response) = try await receive(request, maximumBytes: maximumBytes)
        guard !data.isEmpty, let mime = response.mimeType, mimeTypes.contains(mime)
        else { throw TransportFailure.unexpectedResourceType }
        return data
    }

    private func receive(_ request: URLRequest, maximumBytes: Int) async throws -> (Data, HTTPURLResponse) {
        let (bytes, response) = try await session.bytes(for: request)
        defer { bytes.task.cancel() }
        guard let response = response as? HTTPURLResponse else { throw TransportFailure.invalidResponse }
        guard response.expectedContentLength <= maximumBytes else { throw TransportFailure.responseTooLarge }
        let data = try await readBounded(bytes, maximumBytes: maximumBytes)
        guard (200 ... 299).contains(response.statusCode) else {
            throw HTTPFailure.decode(status: response.statusCode, data: data)
        }
        return (data, response)
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

    private func readBounded(_ bytes: URLSession.AsyncBytes, maximumBytes: Int? = nil) async throws -> Data {
        let limit = maximumBytes ?? maximumResponseBytes
        var data = Data()
        for try await byte in bytes {
            try Task.checkCancellation()
            guard data.count < limit else { throw TransportFailure.responseTooLarge }
            data.append(byte)
        }
        return data
    }

    private func makeRequest(
        method: String, path: String, bearer: String?, json: Data?, form: [String: String]?,
        query: [String: String], accept: String, repeatedQuery: [String: [String]] = [:],
        multipart: MultipartUpload? = nil
    ) throws -> URLRequest {
        guard ["GET", "POST", "PUT", "PATCH", "DELETE"].contains(method),
              [json != nil, form != nil, multipart != nil].filter(\.self).count <= 1,
              method != "GET" || (json == nil && form == nil && multipart == nil)
        else { throw TransportFailure.invalidRequest }
        var request = try URLRequest(url: endpoint.url(path: path, query: query, repeatedQuery: repeatedQuery))
        request.httpMethod = method
        request.timeoutInterval = accept == "text/event-stream" ? idleTimeout : 30
        request.setValue(accept, forHTTPHeaderField: "Accept")
        if let bearer {
            guard !bearer.isEmpty, !bearer.contains(where: { $0 == "\r" || $0 == "\n" }) else {
                throw TransportFailure.invalidRequest
            }
            request.setValue("Bearer \(bearer)", forHTTPHeaderField: "Authorization")
        }
        if let multipart {
            request.httpBody = multipart.body
            request.setValue(multipart.contentType, forHTTPHeaderField: "Content-Type")
        } else if let json {
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
