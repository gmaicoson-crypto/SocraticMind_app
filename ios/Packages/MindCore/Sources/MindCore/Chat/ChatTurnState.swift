import Foundation

public enum ChatTurnPhase: Sendable {
    case restoring, ready, preparing, sending, verifying, stopping, unresolved, storageFailed
}

public struct ChatTurnReceipt: Equatable, Sendable {
    public let pending: PendingChatTurn
    public let status: ChatTurnStatus?
    public let messages: [StoredChatMessage]
}

public struct ChatTurnState: Sendable {
    public internal(set) var account: HistoryAccount?
    public internal(set) var target: ChatTarget?
    public internal(set) var phase: ChatTurnPhase = .restoring
    public internal(set) var draft = ""
    public internal(set) var pending: PendingChatTurn?
    public internal(set) var submitted = ""
    public internal(set) var partial = ""
    public internal(set) var ids: ChatMessageIDs?
    public internal(set) var notice: String?
    public internal(set) var receipt: ChatTurnReceipt?

    public var editable: Bool {
        account != nil && phase == .ready && pending == nil
    }

    public var characterCount: Int {
        draft.unicodeScalars.count
    }

    public var canSend: Bool {
        editable && receipt == nil && target != nil && !draft.trimmingCharacters(in: .whitespacesAndNewlines)
            .isEmpty && characterCount <= 5000
    }

    public var canStop: Bool {
        pending != nil && [.sending, .verifying, .unresolved].contains(phase)
    }

    public var canVerify: Bool {
        [.unresolved, .storageFailed].contains(phase)
    }
}

/// Live text is bounded and provisional; completion requires server status and stored history.
struct ChatTurnBuffer {
    private var text = ""
    private var bytes = 0
    private var terminal = false
    private(set) var ids: ChatMessageIDs?

    mutating func accept(_ event: ChatEvent) throws {
        switch event {
        case let .text(delta):
            bytes += delta.utf8.count
            guard !terminal, bytes <= 512 * 1024 else { throw ChatTurnFailure.invalidResponse }
            text += delta
        case let .messageIDs(user, ai):
            let next = try ChatMessageIDs(user: user, ai: ai)
            guard ids == nil || ids == next else { throw ChatTurnFailure.invalidResponse }
            ids = next
        case let .requestState(value):
            guard let status = ChatTurnStatus(rawValue: value),
                  !terminal || status.terminal else { throw ChatTurnFailure.invalidResponse }
            terminal = status.terminal
        case .failure, .extensionPayload, .done: break
        }
    }

    var content: String {
        text
    }
}
