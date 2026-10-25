import Foundation

/// Each picker opening has a new identity, so a delayed system picker cannot change another conversation.
public struct ChatAvatarPicker: Equatable, Identifiable, Sendable {
    public let account: HistoryAccount
    public let target: ChatTarget
    public let id = UUID()
}

public struct ChatAvatarSave: Sendable {
    public let target: ChatTarget
    public let expected: ChatAvatarResource?
    public let value: ChatAvatarResource?
    let clearRemote: Bool
}

public struct ChatAvatarState: Sendable {
    public internal(set) var account: HistoryAccount?
    public internal(set) var choices: ChatAvatarChoices?
    public internal(set) var loading = false
    public internal(set) var busy = false
    public internal(set) var picker: ChatAvatarPicker?
    public internal(set) var pendingSave: ChatAvatarSave?
    public internal(set) var notice: String?
    public var loaded: Bool {
        choices != nil
    }

    public func resource(for target: ChatTarget) -> ChatAvatarResource {
        if let pendingSave, pendingSave.target.sessionID.utf8.elementsEqual(target.sessionID.utf8) {
            return pendingSave.value ?? .fallback(for: target.mode)
        }
        return choices?[target.sessionID] ?? .fallback(for: target.mode)
    }
}
