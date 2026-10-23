public protocol ChatHistoryGateway: Sendable {
    func conversations(token: String, mode: ChatMode, limit: Int, cursor: HistoryCursor?) async throws
        -> ChatHistoryPage<ConversationSummary>
    func messages(token: String, sessionID: String, limit: Int, cursor: HistoryCursor?) async throws
        -> ChatHistoryPage<StoredChatMessage>
}
