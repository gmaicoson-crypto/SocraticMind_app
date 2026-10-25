import Foundation
@testable import MindCore
import Testing

struct AvatarImageLoaderTests {
    @Test
    func duplicateCellsShareReadAndOneCancelledWaiterReturnsWithoutCancellingOthers() async throws {
        try await withImages { loader, gateway in
            let finished = ImageCompletion()
            let first = Task {
                let result = await imageResult { try await loader.load(imageResource(0)) }
                await finished.mark(); return result
            }
            let second = Task { try await loader.load(imageResource(0)) }
            let read = try await gateway.next()
            first.cancel()
            try await awaitHistory { await finished.value }
            #expect(await first.value.failure is CancellationError)
            await read.finish(.success(Data([7])))
            #expect(try await second.value == 7)
            #expect(try await loader.load(imageResource(0)) == 7)
            #expect(await gateway.count == 1)
        }
    }

    @Test
    func permitsCoverDownloadAndDecodeAndUniqueQueueHasAHardBound() async throws {
        let decoded = ImageRead(), entered = ImageCompletion()
        defer { Task { await decoded.finish(.success(Data())) } }
        try await withImages(maximumRequests: 3, decode: { data in
            await entered.mark(); _ = try await decoded.result()
            return DecodedAvatar(image: Int(data[0]), bytes: 8)
        }) { loader, gateway in
            let first = Task { try await loader.load(imageResource(0)) }
            let second = Task { try await loader.load(imageResource(1)) }
            let read1 = try await gateway.next(), read2 = try await gateway.next()
            await read1.finish(.success(Data([1])))
            try await awaitHistory { await entered.value }
            let third = Task { try await loader.load(imageResource(2)) }
            // Actor ordering makes registration deterministic before the fourth request.
            try await awaitHistory { await loader.pendingRequestCount == 3 }
            await #expect(throws: AvatarImageFailure.self) { try await loader.load(imageResource(3)) }
            #expect(await gateway.count == 2)
            await decoded.finish(.success(Data()))
            let read3 = try await gateway.next()
            await read2.finish(.success(Data([2]))); await read3.finish(.success(Data([3])))
            _ = try await (first.value, second.value, third.value)
            #expect(await gateway.count == 3)
        }
    }

    @Test
    func cacheUsesAccessOrderAndBothByteAndEntryBudgets() async throws {
        for bytes in [12, 16] {
            try await withImages(maximumBytes: bytes, maximumEntries: 2) { loader, gateway in
                _ = try await fetchImage(0, loader, gateway); _ = try await fetchImage(1, loader, gateway)
                if bytes == 16 {
                    #expect(try await loader.load(imageResource(0)) == 0)
                    _ = try await fetchImage(2, loader, gateway); _ = try await fetchImage(1, loader, gateway)
                    #expect(await gateway.count == 4)
                } else {
                    _ = try await fetchImage(0, loader, gateway)
                    #expect(await gateway.count == 3)
                }
            }
        }
    }

    @Test
    func closingReleasesWaitersAndFencesANonCooperativeDecoder() async throws {
        let decoded = ImageRead(), entered = ImageCompletion()
        defer { Task { await decoded.finish(.success(Data())) } }
        try await withImages(decode: { _ in
            await entered.mark(); _ = try await decoded.result(); return DecodedAvatar(image: 7, bytes: 8)
        }) { loader, gateway in
            let finished = ImageCompletion()
            let old = Task {
                let result = await imageResult { try await loader.load(imageResource(0)) }
                await finished.mark(); return result
            }
            try await gateway.next().finish(.success(Data([7])))
            try await awaitHistory { await entered.value }
            await loader.close()
            try await awaitHistory { await finished.value }
            #expect(await old.value.failure is CancellationError)
            try await withImages { newer, fresh in
                #expect(newer.id != loader.id)
                let fetched = try await fetchImage(0, newer, fresh)
                #expect(fetched == 0)
                await decoded.finish(.success(Data()))
                let cached = try await newer.load(imageResource(0))
                #expect(cached == 0)
            }
            await #expect(throws: CancellationError.self) { try await loader.load(imageResource(0)) }
        }
    }

    @Test
    func failuresAreNotReplayedAndAnExplicitLaterLoadRetries() async throws {
        try await withImages { loader, gateway in
            let failed = Task { await imageResult { try await loader.load(imageResource(0)) } }
            try await gateway.next().finish(.failure(SessionTestError.storage))
            #expect(await failed.value.failure != nil)
            #expect(await gateway.count == 1)
            #expect(try await fetchImage(0, loader, gateway) == 0)
            #expect(await gateway.count == 2)
        }
    }

    @Test
    func rejectsEncodedAndDecodedBudgetsBeforeCaching() async throws {
        let decoded = ImageCounter()
        try await withImages(maximumBytes: 8, decode: { _ in
            await decoded.increment(); return DecodedAvatar(image: 1, bytes: 9)
        }) { loader, gateway in
            for data in [Data(), Data(repeating: 0, count: ChatAvatarResource.maximumImageBytes + 1), Data([1])] {
                let request = Task { await imageResult { try await loader.load(imageResource(0)) } }
                try await gateway.next().finish(.success(data))
                #expect(await request.value.failure != nil)
            }
            #expect(await decoded.value == 1); #expect(await gateway.count == 3)
        }
    }

    @Test
    func closeStopsQueuedNetworkWorkAndReleasesAllCallers() async throws {
        try await withImages { loader, gateway in
            let requests = (0 ..< 4).map { index in
                Task { await imageResult { try await loader.load(imageResource(index)) } }
            }
            _ = try await gateway.next(); _ = try await gateway.next()
            try await awaitHistory { await loader.pendingRequestCount == 4 }
            await loader.close()
            for request in requests {
                #expect(await request.value.failure is CancellationError)
            }
            #expect(await gateway.count == 2)
        }
    }
}

private func imageResource(_ index: Int) throws -> ChatAvatarResource {
    try ChatAvatarResource(ChatAvatarResource.presets(for: .normal)[index])
}

private func fetchImage(_ index: Int, _ loader: AvatarImageLoader<Int>, _ gateway: ImageGateway) async throws -> Int {
    let request = Task { try await loader.load(imageResource(index)) }
    try await gateway.next().finish(.success(Data([UInt8(index)])))
    return try await request.value
}

private func withImages(maximumBytes: Int = 16, maximumEntries: Int = 2, maximumRequests: Int = 64,
                        decode: @escaping @Sendable (Data) async throws -> DecodedAvatar<Int> = {
                            DecodedAvatar(image: Int($0[0]), bytes: 8)
                        },
                        body: (AvatarImageLoader<Int>, ImageGateway) async throws -> Void) async throws
{
    let gateway = ImageGateway()
    let loader = AvatarImageLoader(account: HistoryAccount(userID: 1, revision: 1), gateway: gateway,
                                   maximumBytes: maximumBytes, maximumEntries: maximumEntries,
                                   maximumRequests: maximumRequests, decode: decode)
    do { try await body(loader, gateway) } catch {
        await loader.close(); await gateway.close(); throw error
    }
    await loader.close(); await gateway.close()
}

private actor ImageRead {
    private var continuation: CheckedContinuation<Data, Error>?
    private var response: Result<Data, Error>?
    func result() async throws -> Data {
        if let response {
            return try response.get()
        }
        return try await withCheckedThrowingContinuation { continuation = $0 }
    }

    func finish(_ value: Result<Data, Error>) {
        guard response == nil else { return }
        response = value; continuation?.resume(with: value); continuation = nil
    }
}

private actor ImageGateway: ChatAvatarGateway {
    private var calls: [ImageRead] = [], pending: [ImageRead] = []
    private(set) var count = 0
    func image(_: ChatAvatarResource) async throws -> Data {
        let read = ImageRead(); count += 1; calls.append(read); pending.append(read)
        return try await read.result()
    }

    nonisolated func next() async throws -> ImageRead {
        try await awaitHistory { await self.available }
        return await pop()
    }

    private func pop() -> ImageRead {
        calls.removeFirst()
    }

    private var available: Bool {
        !calls.isEmpty
    }

    func close() async {
        for call in pending {
            await call.finish(.failure(CancellationError()))
        }
    }

    func upload(token _: String, ownerID _: Int64, sessionID _: String, data _: Data,
                format _: AvatarImageFormat) async throws -> ChatAvatarResource
    {
        throw SessionTestError.storage
    }

    func delete(token _: String, sessionID _: String) async throws -> Int64 {
        throw SessionTestError.storage
    }
}

private actor ImageCompletion {
    private(set) var value = false
    func mark() {
        value = true
    }
}

private actor ImageCounter {
    private(set) var value = 0
    func increment() {
        value += 1
    }
}

private func imageResult(_ operation: () async throws -> Int) async -> Result<Int, Error> {
    do { return try await .success(operation()) } catch { return .failure(error) }
}

private extension Result {
    var failure: Failure? {
        if case let .failure(error) = self {
            error
        } else {
            nil
        }
    }
}
