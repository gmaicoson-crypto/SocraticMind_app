package com.gmaicoson.socraticmind.chat

import com.gmaicoson.socraticmind.network.HttpTransport
import com.gmaicoson.socraticmind.network.MultipartUpload
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

interface ChatAvatarGateway {
    suspend fun upload(
        token: String,
        ownerId: Long,
        sessionId: String,
        bytes: ByteArray,
        format: AvatarImageFormat,
    ): ChatAvatarResource

    suspend fun delete(
        token: String,
        sessionId: String,
    ): Long

    suspend fun image(resource: ChatAvatarResource): ByteArray
}

class ChatAvatarApi(
    private val transport: HttpTransport,
) : ChatAvatarGateway {
    override suspend fun upload(
        token: String,
        ownerId: Long,
        sessionId: String,
        bytes: ByteArray,
        format: AvatarImageFormat,
    ): ChatAvatarResource {
        require(ownerId > 0)
        requireSessionId(sessionId)
        require(sessionId == sessionId.trim())
        val result =
            transport
                .request(
                    "POST",
                    "api/chat/avatar",
                    bearer = token,
                    multipart =
                        MultipartUpload(
                            mapOf("session_id" to sessionId),
                            "file",
                            "avatar.${format.extension}",
                            format.mimeType,
                            bytes,
                        ),
                ).historyObject()
        return ChatAvatarResource(result.historyString("avatar_url")).also {
            require(it.uploaded && it.belongsTo(ownerId, sessionId))
        }
    }

    override suspend fun delete(
        token: String,
        sessionId: String,
    ): Long {
        requireSessionId(sessionId)
        require(sessionId == sessionId.trim())
        return transport
            .request(
                "DELETE",
                "api/chat/avatar",
                bearer = token,
                json = buildJsonObject { put("session_id", sessionId) },
            ).historyObject()
            .historyLong("deleted")
            .also { require(it >= 0) }
    }

    override suspend fun image(resource: ChatAvatarResource): ByteArray =
        transport.resource(
            resource.path,
            AvatarImageFormat.entries.map { it.mimeType }.toSet(),
            ChatAvatarResource.MAXIMUM_IMAGE_BYTES,
        )
}
