package com.gmaicoson.socraticmind.chat

import com.gmaicoson.socraticmind.network.HttpTransport
import kotlinx.serialization.json.JsonElement
import java.util.Collections

enum class ChatModelSource(
    val wireValue: String,
) {
    ENVIRONMENT("environment"),
    CUSTOM("custom"),
}

/** A configuration ID is the identity; multiple configurations may use the same upstream model. */
data class ChatModelOption(
    val id: String,
    val name: String,
    val model: String,
    val source: ChatModelSource,
) {
    init {
        requireModelId(id)
        require(listOf(name, model).all { it.isNotBlank() && it.codePointCount(0, it.length) <= 200 })
    }
}

class ChatModelCatalog(
    models: List<ChatModelOption>,
) {
    val models: List<ChatModelOption> = Collections.unmodifiableList(models.toList())

    init {
        require(models.size <= 256 && models.map { it.id }.distinct().size == models.size)
        require(models.sumOf { (it.id + it.name + it.model).toByteArray(Charsets.UTF_8).size } <= 256 * 1024)
    }

    companion object {
        fun decode(value: JsonElement): ChatModelCatalog =
            ChatModelCatalog(
                value.historyObject().historyArray("models").map {
                    val row = it.historyObject()
                    ChatModelOption(
                        row.historyString("id"),
                        row.historyString("name"),
                        row.historyString("model"),
                        ChatModelSource.entries.single { source -> source.wireValue == row.historyString("source") },
                    )
                },
            )
    }
}

internal fun requireModelId(value: String?) {
    require(value == null || (value.isNotBlank() && value.codePointCount(0, value.length) <= 100))
}

interface ChatModelGateway {
    suspend fun catalog(token: String): ChatModelCatalog
}

class ChatModelApi(
    private val transport: HttpTransport,
) : ChatModelGateway {
    override suspend fun catalog(token: String): ChatModelCatalog =
        ChatModelCatalog.decode(transport.request("GET", "api/llm/models", bearer = token))
}

data class ChatModelState(
    val account: HistoryAccount? = null,
    val catalog: ChatModelCatalog? = null,
    val selected: ChatModelOption? = null,
    val loading: Boolean = false,
    val notice: String? = null,
) {
    val selectedId: String? get() = selected?.id
    val label: String get() = selected?.name ?: "服务端默认"
    val available: Boolean get() = selected == null || catalog?.models?.any { it.id == selected.id } == true
}
