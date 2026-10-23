package com.gmaicoson.socraticmind.network

import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrl

/** Production defaults to HTTPS. Development must name each allowed cleartext host. */
class ApiEndpoint(
    baseUrl: String,
    developmentHttpHosts: Set<String> = emptySet(),
) {
    private val base = baseUrl.toHttpUrl()
    val credentialScope: String get() = base.toString()

    init {
        require(base.isHttps || base.host in developmentHttpHosts) { "HTTPS is required" }
        require(base.username.isEmpty() && base.password.isEmpty()) { "Credentials do not belong in an API URL" }
        require(base.query == null && base.fragment == null) { "API base cannot contain query or fragment" }
        require(base.encodedPath.endsWith('/')) { "API base path must end in /" }
    }

    fun url(
        path: String,
        query: Map<String, String> = emptyMap(),
        repeatedQuery: Map<String, List<String>> = emptyMap(),
    ): HttpUrl {
        require(query.keys.intersect(repeatedQuery.keys).isEmpty()) { "Ambiguous query parameters" }
        val parts = path.removePrefix("/").split('/')
        require(parts.all { it.isNotEmpty() && it != "." && it != ".." }) { "Invalid API path" }
        require(path.none { it in "?#\\%" }) { "Use separate path and query arguments" }
        return base
            .newBuilder()
            .apply {
                parts.forEach(::addPathSegment)
                query.toSortedMap().forEach { (name, value) -> addQueryParameter(name, value) }
                repeatedQuery.toSortedMap().forEach { (name, values) ->
                    values.forEach { addQueryParameter(name, it) }
                }
            }.build()
    }
}
