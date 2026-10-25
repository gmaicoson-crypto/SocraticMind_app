package com.gmaicoson.socraticmind.network

import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.channels.trySendBlocking
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.buffer
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import okhttp3.Call
import okhttp3.Callback
import okhttp3.ConnectionPool
import okhttp3.FormBody
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import java.io.ByteArrayOutputStream
import java.io.Closeable
import java.io.IOException
import java.util.concurrent.TimeUnit
import kotlin.coroutines.resumeWithException

/** App-scoped connection pool. Cancellation closes transport; server cancellation is a separate API. */
class HttpTransport(
    private val endpoint: ApiEndpoint,
    idleTimeoutMillis: Long = 90_000,
    private val maximumResponseBytes: Int = 1024 * 1024,
) : Closeable {
    private val client =
        OkHttpClient
            .Builder()
            .followRedirects(false)
            .followSslRedirects(false)
            .retryOnConnectionFailure(false)
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(idleTimeoutMillis, TimeUnit.MILLISECONDS)
            .build()
    private val finiteClient = client.newBuilder().callTimeout(30, TimeUnit.SECONDS).build()

    // A stale idle socket can fail after a mutation was sent. Avoid ambiguous POST replay;
    // reads keep the shared pool, while mutation connections are discarded when idle.
    private val mutationClient = client.newBuilder().connectionPool(ConnectionPool(0, 1, TimeUnit.SECONDS)).build()
    private val finiteMutationClient = mutationClient.newBuilder().callTimeout(30, TimeUnit.SECONDS).build()

    init {
        require(idleTimeoutMillis > 0 && maximumResponseBytes > 0)
    }

    suspend fun request(
        method: String,
        path: String,
        bearer: String? = null,
        json: JsonElement? = null,
        form: Map<String, String>? = null,
        query: Map<String, String> = emptyMap(),
        repeatedQuery: Map<String, List<String>> = emptyMap(),
        multipart: MultipartUpload? = null,
    ): JsonElement =
        execute(
            buildRequest(method, path, bearer, json, form, query, "application/json", repeatedQuery, multipart),
            maximumResponseBytes,
        ) { response, bytes ->
            if (bytes.isNotEmpty() &&
                response.body.contentType()?.let { "${it.type}/${it.subtype}" } != "application/json"
            ) {
                throw TransportFailure("Expected a JSON response")
            }
            if (bytes.isEmpty()) {
                JsonNull
            } else {
                Json.parseToJsonElement(
                    bytes.decodeToString(throwOnInvalidSequence = true),
                )
            }
        }

    /** Public same-endpoint resources only; no bearer token, cookies or redirect following. */
    suspend fun resource(
        path: String,
        mimeTypes: Set<String>,
        maximumBytes: Int,
    ): ByteArray {
        require(maximumBytes in 1..(5 * 1024 * 1024))
        require(mimeTypes.isNotEmpty() && mimeTypes.all { it.matches(Regex("[a-z0-9.+_-]+/[a-z0-9.+_-]+")) })
        return execute(
            buildRequest("GET", path, null, null, null, emptyMap(), mimeTypes.sorted().joinToString(", ")),
            maximumBytes,
        ) { response, bytes ->
            val mime = response.body.contentType()?.let { "${it.type}/${it.subtype}" }
            if (bytes.isEmpty() || mime !in mimeTypes) throw TransportFailure("Unexpected resource type")
            bytes
        }
    }

    private suspend fun <T> execute(
        request: Request,
        maximumBytes: Int,
        decode: (Response, ByteArray) -> T,
    ): T =
        suspendCancellableCoroutine { continuation ->
            val requestClient = if (request.method == "GET") finiteClient else finiteMutationClient
            val call = requestClient.newCall(request)
            continuation.invokeOnCancellation { call.cancel() }
            call.enqueue(
                object : Callback {
                    override fun onFailure(
                        call: Call,
                        e: IOException,
                    ) {
                        if (continuation.isActive) continuation.resumeWithException(e)
                    }

                    override fun onResponse(
                        call: Call,
                        response: Response,
                    ) {
                        try {
                            response.use {
                                val bytes = readBounded(it, maximumBytes)
                                if (!it.isSuccessful) throw HttpFailure.from(it.code, bytes)
                                val value = decode(it, bytes)
                                if (continuation.isActive) continuation.resumeWith(Result.success(value))
                            }
                        } catch (error: Exception) {
                            if (continuation.isActive) continuation.resumeWithException(error)
                        }
                    }
                },
            )
        }

    fun stream(
        path: String,
        bearer: String,
        json: JsonElement,
    ): Flow<ChatEvent> =
        callbackFlow {
            val call =
                mutationClient.newCall(
                    buildRequest("POST", path, bearer, json, null, emptyMap(), "text/event-stream"),
                )
            call.enqueue(
                object : Callback {
                    override fun onFailure(
                        call: Call,
                        e: IOException,
                    ) {
                        this@callbackFlow.close(e)
                    }

                    override fun onResponse(
                        call: Call,
                        response: Response,
                    ) {
                        val decoder = SseDecoder()
                        try {
                            response.use {
                                if (!it.isSuccessful) throw HttpFailure.from(it.code, readBounded(it))
                                if (it.body.contentType()?.let { type -> "${type.type}/${type.subtype}" } !=
                                    "text/event-stream"
                                ) {
                                    throw TransportFailure("Expected an SSE response")
                                }
                                val source = it.body.byteStream()
                                val buffer = ByteArray(4096)
                                while (true) {
                                    val count = source.read(buffer)
                                    if (count < 0) throw TransportFailure("Stream ended before DONE")
                                    for (payload in decoder.feed(buffer.copyOf(count))) {
                                        for (event in ChatEventDecoder.decode(payload)) {
                                            trySendBlocking(event).getOrThrow()
                                            if (event == ChatEvent.Done) {
                                                this@callbackFlow.close()
                                                return
                                            }
                                        }
                                    }
                                }
                            }
                        } catch (error: Exception) {
                            this@callbackFlow.close(error)
                        } finally {
                            decoder.finish()
                        }
                    }
                },
            )
            awaitClose { call.cancel() }
        }.buffer(32)

    private fun buildRequest(
        method: String,
        path: String,
        bearer: String?,
        json: JsonElement?,
        form: Map<String, String>?,
        query: Map<String, String>,
        accept: String,
        repeatedQuery: Map<String, List<String>> = emptyMap(),
        multipart: MultipartUpload? = null,
    ): Request {
        require(method in setOf("GET", "POST", "PUT", "PATCH", "DELETE"))
        require(listOf(json, form, multipart).count { it != null } <= 1)
        require(method != "GET" || (json == null && form == null && multipart == null))
        val body =
            when {
                multipart != null -> multipart.body
                form != null -> FormBody.Builder().apply { form.forEach { (key, value) -> add(key, value) } }.build()
                json != null -> json.toString().toRequestBody("application/json; charset=utf-8".toMediaType())
                method in setOf("POST", "PUT", "PATCH") -> ByteArray(0).toRequestBody()
                else -> null
            }
        return Request
            .Builder()
            .url(endpoint.url(path, query, repeatedQuery))
            .method(method, body)
            .header("Accept", accept)
            .apply {
                if (bearer != null) {
                    require(bearer.isNotBlank())
                    header("Authorization", "Bearer $bearer")
                }
            }.build()
    }

    private fun readBounded(
        response: Response,
        maximumBytes: Int = maximumResponseBytes,
    ): ByteArray {
        if (response.body.contentLength() > maximumBytes) throw TransportFailure("Response size limit exceeded")
        val output = ByteArrayOutputStream()
        val buffer = ByteArray(4096)
        val source = response.body.byteStream()
        while (true) {
            val count = source.read(buffer)
            if (count < 0) return output.toByteArray()
            if (count > maximumBytes - output.size()) throw TransportFailure("Response size limit exceeded")
            output.write(buffer, 0, count)
        }
    }

    override fun close() {
        client.dispatcher.cancelAll()
        client.connectionPool.evictAll()
        mutationClient.connectionPool.evictAll()
        client.dispatcher.executorService.shutdown()
    }
}
