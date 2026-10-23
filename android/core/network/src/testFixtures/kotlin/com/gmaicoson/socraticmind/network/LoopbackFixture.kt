package com.gmaicoson.socraticmind.network

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.io.Closeable
import java.nio.file.Files
import java.nio.file.Path
import java.util.concurrent.TimeUnit

/** Starts only the shared synthetic loopback server, never the user's development backend. */
class LoopbackFixture : Closeable {
    private val directory = Files.createTempDirectory("socratic-http-")
    private val ready = directory.resolve("ready.json")
    private val root = Path.of(System.getProperty("socratic.contracts")).parent.parent
    private val process =
        ProcessBuilder(
            "python3",
            root.resolve("scripts/contracts/transport_fixture.py").toString(),
            "--ready-file",
            ready.toString(),
        ).redirectOutput(ProcessBuilder.Redirect.DISCARD)
            .redirectError(directory.resolve("stderr.log").toFile())
            .start()
    val endpoint: ApiEndpoint

    init {
        try {
            val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(10)
            while (!Files.exists(ready) && process.isAlive && System.nanoTime() < deadline) Thread.sleep(20)
            check(
                Files.exists(ready),
            ) { "Loopback fixture failed: ${Files.readString(directory.resolve("stderr.log"))}" }
            val url =
                Json
                    .parseToJsonElement(Files.readString(ready))
                    .jsonObject
                    .getValue("url")
                    .jsonPrimitive.content
            endpoint = ApiEndpoint(url, setOf("127.0.0.1"))
        } catch (error: Exception) {
            close()
            throw error
        }
    }

    override fun close() {
        process.destroy()
        if (!process.waitFor(2, TimeUnit.SECONDS)) process.destroyForcibly().waitFor()
        Files.walk(directory).use { paths -> paths.sorted(Comparator.reverseOrder()).forEach(Files::deleteIfExists) }
    }
}
