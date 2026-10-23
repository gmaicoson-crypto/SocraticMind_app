package com.gmaicoson.socraticmind.network

import java.io.ByteArrayOutputStream

/** Single-stream, bounded data-field parser. Transport and JSON semantics stay separate. */
class SseDecoder(
    private val maxLineBytes: Int = 64 * 1024,
    private val maxEventBytes: Int = 256 * 1024,
) {
    private val line = ByteArrayOutputStream()
    private val data = mutableListOf<String>()
    private var eventBytes = 0
    private var skipLineFeed = false
    private var firstLine = true
    private var closed = false

    init {
        require(maxLineBytes > 0 && maxEventBytes > 0)
    }

    fun feed(bytes: ByteArray): List<String> {
        check(!closed) { "SSE decoder is closed" }
        val events = mutableListOf<String>()
        try {
            for (byte in bytes) {
                val value = byte.toInt() and 0xff
                if (skipLineFeed && value == 10) {
                    skipLineFeed = false
                    continue
                }
                skipLineFeed = false
                when (value) {
                    10, 13 -> {
                        consumeLine(events)
                        skipLineFeed = value == 13
                    }

                    else -> {
                        require(line.size() < maxLineBytes) { "SSE line limit exceeded" }
                        line.write(value)
                    }
                }
            }
        } catch (error: Exception) {
            finish()
            throw error
        }
        return events
    }

    /** EOF does not dispatch an event without a blank line; caller must reconcile request state. */
    fun finish() {
        closed = true
        line.reset()
        data.clear()
        eventBytes = 0
    }

    private fun consumeLine(events: MutableList<String>) {
        val size = line.size()
        var text = line.toByteArray().decodeToString(throwOnInvalidSequence = true)
        line.reset()
        if (firstLine) {
            text = text.removePrefix("\uFEFF")
            firstLine = false
        }
        if (text.isEmpty()) {
            if (data.isNotEmpty()) events.add(data.joinToString("\n"))
            data.clear()
            eventBytes = 0
            return
        }
        require(size <= maxEventBytes - eventBytes) { "SSE event limit exceeded" }
        eventBytes += size
        val separator = text.indexOf(':')
        val field = if (separator < 0) text else text.substring(0, separator)
        if (field == "data") {
            val value = if (separator < 0) "" else text.substring(separator + 1).removePrefix(" ")
            data.add(value)
        }
    }
}
