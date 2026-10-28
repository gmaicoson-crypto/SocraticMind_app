package com.gmaicoson.socraticmind.learning

import com.gmaicoson.socraticmind.network.HttpFailure
import com.gmaicoson.socraticmind.network.HttpTransport
import com.gmaicoson.socraticmind.network.LoopbackFixture
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertThrows
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import java.nio.file.Files
import java.nio.file.Path

private fun fixture(name: String) =
    Json
        .parseToJsonElement(
            Files.readString(Path.of(System.getProperty("socratic.contracts")).resolve(name)),
        ).obj()

class OnboardingApiContractTest {
    private val data = fixture("onboarding-runs.json")
    private val wire = fixture("onboarding-wire.json")
    private val id = OnboardingID(data.getValue("request").obj().text("run_id", 36))
    private val form = decodeForm(data.getValue("request"))

    @Test
    fun `cancel before creation decodes terminal reservation through new HTTP path`() =
        runBlocking {
            val fixture = fixture("onboarding-cancellation.json")
            val reserved = OnboardingID(fixture.text("run_id", 36))
            LoopbackFixture().use { server ->
                HttpTransport(server.endpoint).use { transport ->
                    val run = OnboardingApi(transport).cancel("onboarding-cancel-before-create", reserved)
                    assertEquals(OnboardingStatus.CANCELLED, run.status)
                    assertEquals(1, run.version)
                    assertNull(run.input)
                    assertEquals(reserved, run.id)
                }
            }
        }

    @Test
    fun `provider states project diagnosis preview and terminal results`() {
        val responses = data.getValue("responses").obj()
        for ((_, value) in responses) {
            val row = value.obj()
            val run = OnboardingRun.decode(value, OnboardingID(row.text("run_id", 36)))
            assertEquals(row.text("status", 40), run.status.wire)
            assertEquals(row.number("version").toInt(), run.version)
            assertEquals(row.flag("processing"), run.processing)
        }
        val preview = OnboardingRun.decode(responses.getValue("preview"), id).preview!!
        assertEquals(6, preview.nodes.size)
        assertEquals(120, preview.totalMinutes)
        assertEquals("Asia/Shanghai", preview.timezone)
        assertEquals(65, preview.diagnostic!!.score)
        assertEquals(20, OnboardingRun.decode(responses.getValue("edited"), id).input!!.dailyMinutes)
        assertEquals(1L, OnboardingRun.decode(responses.getValue("completed"), id).result!!.topicId)
    }

    @Test
    fun `invalid identity versions dates references and bounded collections fail closed`() {
        for (entry in wire.list("invalid", 100)) {
            val row = entry.obj()
            assertThrows(RuntimeException::class.java, {
                OnboardingRun.decode(Json.parseToJsonElement(row.text("wire", 1_048_576)), id)
            }, row.text("id", 80))
        }
    }

    @Test
    fun `unknown fields and legacy terminal payloads preserve safe recovery`() {
        for (entry in wire.list("valid", 20)) {
            val row = entry.obj()
            val value = row.getValue("response").obj()
            val run = OnboardingRun.decode(value, OnboardingID(value.text("run_id", 36)))
            when (row.text("id", 80)) {
                "unicode-identities" -> {
                    assertEquals(
                        6,
                        run.preview!!
                            .nodes
                            .map { it.key }
                            .distinct()
                            .size,
                    )
                }

                "unknown-error" -> {
                    assertNull(run.error!!.code)
                    assertTrue(run.error.retryable)
                }

                "legacy-cancelled" -> {
                    assertNull(run.input)
                    assertNull(run.preview)
                    assertEquals(OnboardingStatus.CANCELLED, run.status)
                }
            }
        }
    }

    @Test
    fun `form uses scalar limits real calendar dates and canonical path identifiers`() {
        assertEquals(200, form.copy(topic = "🙂".repeat(200)).topic.codePointCount(0, 400))
        assertThrows(IllegalArgumentException::class.java) { form.copy(topic = "🙂".repeat(201)) }
        for (date in listOf("2000-02-29", "2026-12-31", "0001-01-01")) form.copy(targetDate = date)
        for (date in listOf("1900-02-29", "2026-02-30", "2026-1-01", "0000-01-01")) {
            assertThrows(RuntimeException::class.java) { form.copy(targetDate = date) }
        }
        for (value in listOf("", "../runs", id.value.uppercase(), id.value + "\n")) {
            assertThrows(IllegalArgumentException::class.java) { OnboardingID(value) }
        }
        assertEquals(36, OnboardingID.create().value.length)
    }

    @Test
    fun `all mutations carry exact fields versions and explicit date clearing`(): Unit =
        runBlocking {
            LoopbackFixture().use { server ->
                HttpTransport(server.endpoint).use { transport ->
                    val api = OnboardingApi(transport)
                    assertEquals(OnboardingStatus.DIAGNOSING, api.start("onboarding-start", id, form).status)
                    assertEquals(OnboardingStatus.DIAGNOSING, api.start("onboarding-model", id, form, "用户配置-é").status)
                    assertTrue(api.read("onboarding-read", id).processing)
                    val responses = data.getValue("responses").obj()
                    val step = responses.getValue("diagnosing").obj()
                    val preview =
                        api.answer(
                            "onboarding-answer",
                            id,
                            step.number("version").toInt(),
                            step.getValue("step").obj().text("step_id", 100),
                            " 先表示向量 ",
                        )
                    assertEquals(OnboardingStatus.PREVIEW, preview.status)
                    val edited =
                        api.revise(
                            "onboarding-revise",
                            id,
                            preview.version,
                            form.goal,
                            20,
                            null,
                            form.timezone,
                        )
                    assertEquals(20, edited.preview!!.dailyMinutes)
                    assertNull(edited.input!!.targetDate)
                    val completed = api.confirm("onboarding-confirm", id, edited.version, "fixture-confirm")
                    assertEquals(OnboardingStatus.COMPLETED, completed.status)
                    assertFalse(completed.processing)
                    assertEquals(OnboardingStatus.CANCELLED, api.cancel("onboarding-cancel", id).status)
                    assertEquals(OnboardingStatus.DIAGNOSING, api.retry("onboarding-retry", id, 2).status)
                }
            }
        }

    @Test
    fun `http errors remain distinguishable and confirmation is never automatically retried`(): Unit =
        runBlocking {
            LoopbackFixture().use { server ->
                HttpTransport(server.endpoint).use { transport ->
                    val api = OnboardingApi(transport)
                    for ((name, status) in listOf(
                        "unauthorized" to 401,
                        "missing" to 404,
                        "conflict" to 409,
                        "unavailable" to 503,
                    )) {
                        val failure = runCatching { api.read("onboarding-$name", id) }.exceptionOrNull() as HttpFailure
                        assertEquals(status, failure.status)
                    }
                    val version =
                        data
                            .getValue("responses")
                            .obj()
                            .getValue("edited")
                            .obj()
                            .number("version")
                            .toInt()
                    val failure =
                        runCatching {
                            api.confirm("onboarding-confirm-conflict", id, version, "fixture-confirm")
                        }.exceptionOrNull() as HttpFailure
                    assertEquals("AGENT_STATE_CONFLICT", failure.code)
                    val stats =
                        transport
                            .request(
                                "GET",
                                "stats",
                                query = mapOf("id" to "onboarding-confirm-conflict"),
                            ).obj()
                    assertEquals(1L, stats.number("count"))
                }
            }
        }

    @Test
    fun `raw malformed json numbers remain invalid through real transport`(): Unit =
        runBlocking {
            LoopbackFixture().use { server ->
                HttpTransport(server.endpoint).use { transport ->
                    val api = OnboardingApi(transport)
                    for (entry in wire.list("invalid", 100)) {
                        val name = entry.obj().text("id", 80)
                        assertTrue(
                            runCatching { api.read("onboarding-$name", id) }.exceptionOrNull() is RuntimeException,
                            name,
                        )
                    }
                }
            }
        }
}
