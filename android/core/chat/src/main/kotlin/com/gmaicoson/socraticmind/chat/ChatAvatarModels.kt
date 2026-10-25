package com.gmaicoson.socraticmind.chat

import java.security.MessageDigest

enum class ChatAvatarFailure { INVALID_RECORD, CONFLICT, CAPACITY }

class ChatAvatarException(
    val failure: ChatAvatarFailure,
) : Exception(failure.name)

enum class AvatarImageFormat(
    val extension: String,
    val mimeType: String,
) {
    PNG("png", "image/png"),
    JPEG("jpeg", "image/jpeg"),
    GIF("gif", "image/gif"),
    WEBP("webp", "image/webp"),
}

/** Only known bundled presets or backend-generated chat avatar paths; never arbitrary URLs. */
data class ChatAvatarResource(
    val path: String,
) {
    init {
        require(
            path in presets(ChatMode.NORMAL) || path in presets(ChatMode.SOCRATIC) ||
                path.matches(
                    Regex("/static/avatars/ai_[1-9][0-9]*_[a-f0-9]{24}_[a-f0-9]{32}\\.(png|jpg|jpeg|gif|webp)"),
                ),
        )
    }

    val uploaded: Boolean get() = path.startsWith("/static/avatars/")

    fun belongsTo(
        ownerId: Long,
        sessionId: String,
    ): Boolean {
        require(ownerId > 0)
        requireSessionId(sessionId)
        require(sessionId == sessionId.trim())
        if (!uploaded) return true
        val hash =
            MessageDigest
                .getInstance("SHA-256")
                .digest(sessionId.toByteArray(Charsets.UTF_8))
                .joinToString("") { "%02x".format(it) }
                .take(24)
        return path.startsWith("/static/avatars/ai_${ownerId}_${hash}_")
    }

    companion object {
        const val MAXIMUM_IMAGE_BYTES = 5 * 1024 * 1024

        fun presets(mode: ChatMode): List<String> =
            if (mode == ChatMode.NORMAL) {
                (1..6).map { "/avatars/AI/normal/AI_normal${if (it == 1) "" else "_$it"}.webp" }
            } else {
                listOf("female", "male").flatMap { gender -> (1..3).map { "/avatars/AI/study/AI-$gender-$it.webp" } }
            }

        fun default(mode: ChatMode) =
            ChatAvatarResource(
                if (mode == ChatMode.NORMAL) {
                    presets(mode).first()
                } else {
                    "/avatars/AI/study/AI-male-1.webp"
                },
            )
    }
}

interface ChatAvatarStore {
    suspend fun read(ownerId: Long): Map<String, ChatAvatarResource>

    suspend fun replace(
        ownerId: Long,
        sessionId: String,
        expected: ChatAvatarResource?,
        value: ChatAvatarResource?,
    )

    suspend fun clear(ownerId: Long)
}
