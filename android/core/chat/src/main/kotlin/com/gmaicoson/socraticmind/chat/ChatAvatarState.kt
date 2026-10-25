package com.gmaicoson.socraticmind.chat

import java.util.UUID

/** A picker result is tied to one opening, not merely the currently visible conversation. */
class ChatAvatarPicker internal constructor(
    val account: HistoryAccount,
    val target: ChatTarget,
    val id: String = UUID.randomUUID().toString(),
)

class ChatAvatarSave internal constructor(
    val target: ChatTarget,
    val expected: ChatAvatarResource?,
    val value: ChatAvatarResource?,
    val clearRemote: Boolean,
)

data class ChatAvatarState(
    val account: HistoryAccount? = null,
    val choices: Map<String, ChatAvatarResource> = emptyMap(),
    val loaded: Boolean = false,
    val loading: Boolean = false,
    val busy: Boolean = false,
    val picker: ChatAvatarPicker? = null,
    val pendingSave: ChatAvatarSave? = null,
    val notice: String? = null,
) {
    fun resource(target: ChatTarget): ChatAvatarResource {
        val pending = pendingSave?.takeIf { it.target.sessionId == target.sessionId }
        val choice = if (pending != null) pending.value else choices[target.sessionId]
        return choice ?: ChatAvatarResource.default(target.mode)
    }
}
