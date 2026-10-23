package com.gmaicoson.socraticmind.chat.markdown

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withPermit
import kotlinx.coroutines.withContext

/** Own one renderer per account/view lifetime; never put message content in a global or disk cache. */
class MarkdownRenderer internal constructor(
    private val maxEntries: Int,
    private val maxSourceBytes: Int,
    private val parse: (String) -> MarkdownDocument,
) {
    constructor() : this(32, 1024 * 1024, MarkdownParser::parse)

    private data class Entry(
        val document: MarkdownDocument,
        val bytes: Int,
    )

    private val lock = Any()
    private val cache = LinkedHashMap<String, Entry>(16, 0.75f, true)
    private val workers = Semaphore(2)
    private var bytes = 0
    private var generation = 0L

    init {
        require(maxEntries > 0 && maxSourceBytes > 0)
    }

    suspend fun render(source: String): MarkdownDocument =
        withContext(Dispatchers.Default) {
            val context = currentCoroutineContext()
            val ticket =
                synchronized(lock) {
                    context.ensureActive()
                    cache[source]?.let { return@withContext it.document }
                    generation
                }
            val document =
                workers.withPermit {
                    context.ensureActive()
                    parse(source).also { context.ensureActive() }
                }
            val cost = source.toByteArray(Charsets.UTF_8).size
            synchronized(lock) {
                context.ensureActive()
                if (generation != ticket) throw CancellationException("Markdown scope was cleared")
                if (cost <= maxSourceBytes) {
                    bytes -= cache.remove(source)?.bytes ?: 0
                    cache[source] = Entry(document, cost)
                    bytes += cost
                    while (cache.size > maxEntries || bytes > maxSourceBytes) {
                        val oldest = cache.entries.iterator()
                        bytes -= oldest.next().value.bytes
                        oldest.remove()
                    }
                }
            }
            document
        }

    /** Invalidates late, non-cooperative parser results as well as the retained entries. */
    fun clear() =
        synchronized(lock) {
            generation++
            cache.clear()
            bytes = 0
        }
}
