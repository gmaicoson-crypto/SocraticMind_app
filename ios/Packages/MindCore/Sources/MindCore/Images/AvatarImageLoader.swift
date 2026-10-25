import Foundation

public struct DecodedAvatar<Image: Sendable>: Sendable {
    public let image: Image
    public let bytes: Int
    public init(image: Image, bytes: Int) {
        self.image = image; self.bytes = bytes
    }
}

/// Immutable account ownership; closing invalidates every waiter and late decoder result.
public actor AvatarImageLoader<Image: Sendable> {
    public nonisolated let account: HistoryAccount
    public nonisolated let id = UUID()
    private struct Request {
        let id: UUID
        let task: Task<Void, Never>
        var waiters: [UUID: CheckedContinuation<Image, Error>]
    }

    private let gateway: any ChatAvatarGateway
    private let decode: @Sendable (Data) async throws -> DecodedAvatar<Image>
    private let maximumBytes: Int
    private let maximumEntries: Int
    private let maximumRequests: Int
    private let workers = AvatarImageWorkers()
    private var cache: [ChatAvatarResource: DecodedAvatar<Image>] = [:]
    private var order: [ChatAvatarResource] = []
    private var requests: [ChatAvatarResource: Request] = [:]
    private var bytes = 0
    private var closed = false

    /// Internal observation lets concurrency tests wait for registration without timing sleeps.
    var pendingRequestCount: Int {
        requests.count
    }

    public init(account: HistoryAccount, gateway: any ChatAvatarGateway,
                maximumBytes: Int = 8 * 1024 * 1024, maximumEntries: Int = 32, maximumRequests: Int = 64,
                decode: @escaping @Sendable (Data) async throws -> DecodedAvatar<Image>)
    {
        precondition(maximumBytes > 0 && maximumEntries > 0 && maximumRequests > 0)
        self.account = account; self.gateway = gateway; self.decode = decode
        self.maximumBytes = maximumBytes; self.maximumEntries = maximumEntries; self.maximumRequests = maximumRequests
    }

    public func load(_ resource: ChatAvatarResource) async throws -> Image {
        try Task.checkCancellation(); try checkOpen()
        if let value = cache[resource] {
            touch(resource); return value.image
        }
        let waiter = UUID()
        let value: Image = try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { continuation in
                do {
                    try Task.checkCancellation()
                    if requests[resource] == nil {
                        try create(resource)
                    }
                    requests[resource]?.waiters[waiter] = continuation
                } catch { continuation.resume(throwing: error) }
            }
        } onCancel: { Task { await self.cancelWaiter(resource, id: waiter) } }
        try Task.checkCancellation(); try checkOpen()
        return value
    }

    public func close() {
        closed = true; cache.removeAll(); order.removeAll(); bytes = 0
        for request in requests.values {
            request.task.cancel()
            for waiter in request.waiters.values {
                waiter.resume(throwing: CancellationError())
            }
        }
        requests.removeAll()
    }

    private func create(_ resource: ChatAvatarResource) throws {
        guard requests.count < maximumRequests else { throw AvatarImageFailure.queueFull }
        let id = UUID(), gateway = gateway, decode = decode, workers = workers
        let task = Task.detached { [self] in
            do {
                let value = try await workers.run {
                    let data = try await gateway.image(resource)
                    try Task.checkCancellation()
                    guard !data.isEmpty, data.count <= ChatAvatarResource.maximumImageBytes
                    else { throw AvatarImageFailure.invalidImage }
                    let result = try await decode(data)
                    try Task.checkCancellation()
                    return result
                }
                try await accept(value, resource: resource, id: id)
            } catch {
                await failed(resource, id: id, error: error)
            }
        }
        requests[resource] = Request(id: id, task: task, waiters: [:])
    }

    private func accept(_ value: DecodedAvatar<Image>, resource: ChatAvatarResource, id: UUID) throws {
        try checkOpen()
        guard requests[resource]?.id == id else { throw CancellationError() }
        guard (1 ... maximumBytes).contains(value.bytes) else { throw AvatarImageFailure.decodedTooLarge }
        let waiters = requests.removeValue(forKey: resource)?.waiters.values
        cache[resource] = value; bytes += value.bytes; touch(resource)
        while order.count > maximumEntries || bytes > maximumBytes {
            bytes -= cache.removeValue(forKey: order.removeFirst())?.bytes ?? 0
        }
        if let waiters {
            for waiter in waiters {
                waiter.resume(returning: value.image)
            }
        }
    }

    private func failed(_ resource: ChatAvatarResource, id: UUID, error: Error) {
        guard requests[resource]?.id == id, let request = requests.removeValue(forKey: resource) else { return }
        for waiter in request.waiters.values {
            waiter.resume(throwing: error)
        }
    }

    private func cancelWaiter(_ resource: ChatAvatarResource, id: UUID) {
        requests[resource]?.waiters.removeValue(forKey: id)?.resume(throwing: CancellationError())
    }

    private func touch(_ resource: ChatAvatarResource) {
        order.removeAll { $0 == resource }; order.append(resource)
    }

    private func checkOpen() throws {
        if closed {
            throw CancellationError()
        }
    }
}

/// A permit covers downloading and decoding, including suspension during network IO.
private actor AvatarImageWorkers {
    private var active = 0
    private var waiters: [(UUID, CheckedContinuation<Void, Error>)] = []

    func run<Value: Sendable>(_ operation: @Sendable () async throws -> Value) async throws -> Value {
        try await acquire()
        defer { release() }
        try Task.checkCancellation()
        return try await operation()
    }

    private func acquire() async throws {
        try Task.checkCancellation()
        if active < 2 {
            active += 1; return
        }
        let id = UUID()
        try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { waiters.append((id, $0)) }
        } onCancel: { Task { await self.cancel(id) } }
    }

    private func release() {
        if waiters.isEmpty {
            active -= 1
        } else {
            waiters.removeFirst().1.resume()
        }
    }

    private func cancel(_ id: UUID) {
        guard let index = waiters.firstIndex(where: { $0.0 == id }) else { return }
        waiters.remove(at: index).1.resume(throwing: CancellationError())
    }
}
