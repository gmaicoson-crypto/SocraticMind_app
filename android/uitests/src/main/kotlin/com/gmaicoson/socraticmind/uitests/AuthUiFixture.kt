package com.gmaicoson.socraticmind.uitests

import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URI

internal object AuthUiFixture {
    fun account(): JSONObject =
        request("case/android", "POST") ?: error("Start the isolated auth UI fixture on port 8766")

    fun code(purpose: String): String {
        require(purpose in setOf("register", "reset"))
        repeat(20) {
            request("code/android/$purpose")?.let { return it.getString("code") }
            Thread.sleep(250)
        }
        error("No development code for the synthetic UI account")
    }

    private fun request(
        path: String,
        method: String = "GET",
    ): JSONObject? {
        val connection = URI("http://10.0.2.2:8766/$path").toURL().openConnection() as HttpURLConnection
        connection.connectTimeout = 3_000
        connection.requestMethod = method
        connection.readTimeout = 3_000
        connection.instanceFollowRedirects = false
        try {
            if (connection.responseCode != 200) return null
            return connection.inputStream.bufferedReader().use { JSONObject(it.readText()) }
        } finally {
            connection.disconnect()
        }
    }
}
