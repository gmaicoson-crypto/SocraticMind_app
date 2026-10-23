import Foundation
@testable import MindCore

struct TitleRead: Sendable {
    let ids: [String]
    let read: HistoryRead<ChatTitle>
}

actor QueuedTitlesGateway: ChatTitlesGateway {
    private var queue: [TitleRead] = []
    private var all: [TitleRead] = []
    var count: Int {
        all.count
    }

    func titles(token: String, sessionIDs: [String]) async throws -> [ChatTitle] {
        let call = TitleRead(ids: sessionIDs, read: HistoryRead<ChatTitle>(token: token, cursor: nil))
        all.append(call); queue.append(call)
        return try await call.read.result().items
    }

    func next() async throws -> TitleRead {
        let deadline = ContinuousClock.now.advanced(by: .seconds(2))
        while queue.isEmpty {
            guard ContinuousClock.now < deadline else { throw SessionTestError.timeout }
            try await Task.sleep(for: .milliseconds(1))
        }
        return queue.removeFirst()
    }

    func releasePending() async {
        for call in all {
            await call.read.succeed([])
        }
    }
}

func title(_ id: String, status: ChatTitleStatus = .ready,
           text: String? = "标题", retry: Bool = false) throws -> ChatTitle
{
    let object: [String: Any] = ["session_id": id, "title": text as Any? ?? NSNull(),
                                 "status": status.rawValue, "retry_pending": retry]
    return try JSONDecoder().decode(ChatTitle.self, from: JSONSerialization.data(withJSONObject: object))
}
