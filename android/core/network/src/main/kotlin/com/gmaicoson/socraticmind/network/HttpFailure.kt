package com.gmaicoson.socraticmind.network

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import java.io.IOException

class HttpFailure(
    val status: Int,
    val code: String?,
    val userMessage: String,
    val retryable: Boolean?,
) : IOException("HTTP $status") {
    companion object {
        fun from(
            status: Int,
            bytes: ByteArray,
        ): HttpFailure {
            val payload = runCatching { Json.parseToJsonElement(bytes.decodeToString()) as? JsonObject }.getOrNull()

            fun string(key: String): String? = (payload?.get(key) as? JsonPrimitive)?.takeIf { it.isString }?.content
            val validation =
                (payload?.get("detail") as? JsonArray)
                    ?.firstNotNullOfOrNull { issue ->
                        ((issue as? JsonObject)?.get("msg") as? JsonPrimitive)?.takeIf { it.isString }?.content
                    }?.removePrefix("Value error, ")
            return HttpFailure(
                status,
                string("code"),
                string("message") ?: string("detail") ?: validation ?: "请求失败（HTTP $status）",
                (payload?.get("retryable") as? JsonPrimitive)?.booleanOrNull,
            )
        }
    }
}

class TransportFailure(
    message: String,
) : IOException(message)
