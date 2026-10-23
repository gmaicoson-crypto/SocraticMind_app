import Foundation

/// View/account-owned memory only. The separate worker keeps parsing off the main actor and clear responsive.
public actor MarkdownRenderer {
    private struct Entry { let document: MarkdownDocument; let bytes: Int }
    private let maxEntries: Int
    private let maxSourceBytes: Int
    private let worker: MarkdownWorker
    private var cache: [String: Entry] = [:]
    private var order: [String] = []
    private var bytes = 0
    private var generation: UInt64 = 0

    public init() {
        maxEntries = 32; maxSourceBytes = 1024 * 1024
        worker = MarkdownWorker(parse: MarkdownParser.parse)
    }

    init(maxEntries: Int, maxSourceBytes: Int, parse: @escaping @Sendable (String) -> MarkdownDocument) {
        precondition(maxEntries > 0 && maxSourceBytes > 0)
        self.maxEntries = maxEntries; self.maxSourceBytes = maxSourceBytes
        worker = MarkdownWorker(parse: parse)
    }

    public func render(_ source: String) async throws -> MarkdownDocument {
        try Task.checkCancellation()
        if let entry = cache[source] {
            touch(source)
            return entry.document
        }
        let ticket = generation
        let job = Task.detached { [worker] in try await worker.render(source) }
        let document = try await withTaskCancellationHandler {
            try await job.value
        } onCancel: { job.cancel() }
        try Task.checkCancellation()
        guard generation == ticket else { throw CancellationError() }
        let cost = source.utf8.count
        if cost <= maxSourceBytes {
            bytes -= cache.removeValue(forKey: source)?.bytes ?? 0
            cache[source] = Entry(document: document, bytes: cost)
            bytes += cost
            touch(source)
            while order.count > maxEntries || bytes > maxSourceBytes {
                bytes -= cache.removeValue(forKey: order.removeFirst())?.bytes ?? 0
            }
        }
        return document
    }

    public func clear() {
        generation &+= 1
        cache.removeAll(); order.removeAll(); bytes = 0
    }

    private func touch(_ source: String) {
        order.removeAll { $0 == source }
        order.append(source)
    }
}

private actor MarkdownWorker {
    let parse: @Sendable (String) -> MarkdownDocument

    init(parse: @escaping @Sendable (String) -> MarkdownDocument) {
        self.parse = parse
    }

    func render(_ source: String) throws -> MarkdownDocument {
        try Task.checkCancellation()
        let result = parse(source)
        try Task.checkCancellation()
        return result
    }
}
