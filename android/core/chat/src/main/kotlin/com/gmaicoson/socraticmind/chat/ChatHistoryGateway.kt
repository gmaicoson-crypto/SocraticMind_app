package com.gmaicoson.socraticmind.chat

interface ChatHistoryGateway {
    suspend fun conversations(
        token: String,
        mode: ChatMode = ChatMode.NORMAL,
        limit: Int = 30,
        cursor: HistoryCursor? = null,
    ): ChatHistoryPage<ConversationSummary>

    suspend fun messages(
        token: String,
        sessionId: String,
        limit: Int = 30,
        cursor: HistoryCursor? = null,
    ): ChatHistoryPage<StoredChatMessage>
}
