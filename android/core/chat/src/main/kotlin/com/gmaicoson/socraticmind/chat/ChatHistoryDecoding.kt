package com.gmaicoson.socraticmind.chat

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.longOrNull

internal fun requireSessionId(value: String) {
    require(value.isNotBlank() && value.codePointCount(0, value.length) <= 100) { "Invalid session ID" }
}

internal fun JsonElement.historyObject(): JsonObject =
    this as? JsonObject ?: throw IllegalArgumentException("Invalid history object")

internal fun JsonObject.historyArray(key: String): JsonArray =
    this[key] as? JsonArray ?: throw IllegalArgumentException("Invalid history array")

internal fun JsonObject.historyOptional(key: String): JsonElement? = getValue(key).takeUnless { it == JsonNull }

internal fun JsonObject.historyString(key: String): String {
    val value = this[key] as? JsonPrimitive
    require(value != null && value.isString) { "Invalid history string" }
    return value.content
}

internal fun JsonObject.historyLong(key: String): Long {
    val value = this[key] as? JsonPrimitive
    val number = value?.longOrNull
    require(value != null && !value.isString && number != null) { "Invalid history number" }
    return number
}

internal fun JsonObject.historyOptionalString(key: String): String? = historyOptional(key)?.let { historyString(key) }

internal fun JsonObject.historyOptionalLong(key: String): Long? = historyOptional(key)?.let { historyLong(key) }

internal fun <T> decodeHistoryPage(
    value: JsonElement,
    limit: Int,
    cursor: HistoryCursor?,
    decode: (JsonElement) -> T,
    identifier: (T) -> Long,
): ChatHistoryPage<T> {
    val payload = value.historyObject()
    val snapshot = payload.historyLong("snapshot_id")
    val items = payload.historyArray("items").map(decode)
    val nextId = payload.historyOptionalLong("next_before_id")
    val ids = items.map(identifier)
    require(snapshot >= 0 && items.size <= limit) { "Invalid history page size" }
    require(ids.all { it in 1..snapshot } && ids.zipWithNext().all { (a, b) -> a > b }) {
        "History IDs must descend within the snapshot"
    }
    require(cursor == null || (snapshot == cursor.snapshotId && ids.all { it < cursor.beforeId })) {
        "History response changed the requested window"
    }
    require(nextId == null || (ids.isNotEmpty() && nextId == ids.last())) { "Invalid next cursor" }
    return ChatHistoryPage(items, snapshot, nextId?.let { HistoryCursor(snapshot, it) })
}
