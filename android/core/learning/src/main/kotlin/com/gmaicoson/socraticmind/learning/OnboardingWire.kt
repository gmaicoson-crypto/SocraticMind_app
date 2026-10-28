package com.gmaicoson.socraticmind.learning

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.longOrNull

internal fun JsonElement.obj(): JsonObject = this as? JsonObject ?: error("Invalid learning response")

internal fun JsonObject.optional(key: String): JsonElement? = get(key)?.takeUnless { it == JsonNull }

internal fun JsonElement.text(
    maximum: Int,
    blank: Boolean = false,
): String {
    val value = this as? JsonPrimitive ?: error("Invalid learning text")
    require(value.isString)
    require(value.content.codePointCount(0, value.content.length) <= maximum)
    require(blank || value.content.isNotBlank())
    return value.content
}

internal fun JsonObject.text(
    key: String,
    maximum: Int,
) = getValue(key).text(maximum)

internal fun JsonObject.number(
    key: String,
    minimum: Long = 0,
    maximum: Long = Int.MAX_VALUE.toLong(),
): Long {
    val value = getValue(key) as? JsonPrimitive ?: error("Invalid learning number")
    require(!value.isString && value.content.matches(Regex("-?(0|[1-9][0-9]*)")))
    return requireNotNull(value.longOrNull).also { require(it in minimum..maximum) }
}

internal fun JsonObject.flag(key: String): Boolean {
    val value = getValue(key) as? JsonPrimitive ?: error("Invalid learning flag")
    require(!value.isString)
    return requireNotNull(value.booleanOrNull)
}

internal fun JsonObject.list(
    key: String,
    maximum: Int,
): List<JsonElement> =
    (getValue(key) as? JsonArray ?: error("Invalid learning array")).also { require(it.size <= maximum) }

internal fun JsonObject.date(key: String) = text(key, 10).also(::requireDate)

internal fun decodeForm(value: JsonElement): OnboardingForm =
    value.obj().let {
        OnboardingForm(
            it.text("topic", 200),
            it.text("goal", 300),
            it.text("domain", 100),
            LearningOutcome.entries.first { entry -> entry.wire == it.text("outcome_type", 30) },
            LearningFamiliarity.entries.first { entry -> entry.wire == it.text("familiarity", 30) },
            it.text("timezone", 100),
            it.number("daily_minutes", 5, 240).toInt(),
            it.optional("target_date")?.text(10)?.also(::requireDate),
            it.flag("use_diagnostic"),
        )
    }

internal fun decodeOnboarding(
    value: JsonElement,
    expected: OnboardingID,
): OnboardingRun {
    val row = value.obj()
    require(row.text("run_id", 36) == expected.value && row.text("type", 30) == "onboarding")
    val status = OnboardingStatus.entries.first { it.wire == row.text("status", 40) }
    val version = row.number("version").toInt()
    val processing = row.flag("processing")
    require(!processing || status in listOf(OnboardingStatus.DIAGNOSING, OnboardingStatus.DRAFTING))
    val step =
        if (status == OnboardingStatus.DIAGNOSING && !processing) {
            val item = row.getValue("step").obj()
            val total = item.number("total", 1, 20).toInt()
            OnboardingStep(
                item.text("step_id", 100),
                item.text("prompt", 2000),
                item.text("input_type", 30),
                item.list("choices", 20).map { it.text(1000) },
                item.number("current", 1, total.toLong()).toInt(),
                total,
            )
        } else {
            null
        }
    val preview = if (status == OnboardingStatus.PREVIEW) decodePreview(row.getValue("preview")) else null
    val result =
        if (status == OnboardingStatus.COMPLETED) {
            row.getValue("result").obj().let {
                OnboardingResult(
                    it.number("topic_id", 1, 9_007_199_254_740_991),
                    it.number("plan_id", 1, 9_007_199_254_740_991),
                )
            }
        } else {
            null
        }
    val failure =
        row.optional("error")?.obj()?.let {
            val known =
                setOf(
                    "AI_TIMEOUT",
                    "AI_RATE_LIMITED",
                    "AI_UPSTREAM_ERROR",
                    "AI_REQUEST_FAILED",
                    "AI_OUTPUT_LIMIT",
                    "AI_CONTENT_FILTERED",
                    "STRUCTURED_OUTPUT_INVALID",
                    "GRAPH_INVALID",
                    "AGENT_STAGE_UNKNOWN",
                )
            OnboardingRunError(it.text("code", 80).takeIf(known::contains), it.flag("retryable"))
        }
    return OnboardingRun(
        expected,
        status,
        version,
        processing,
        row.optional("input")?.let(::decodeForm),
        step,
        preview,
        result,
        failure,
    )
}

private fun decodePreview(value: JsonElement): OnboardingPreview {
    val row = value.obj()
    val nodes =
        row.list("nodes", 100).map {
            val node = it.obj()
            LearningDraftNode(
                node.text("key", 100),
                node.text("label", 200),
                node.optional("sub")?.text(500, blank = true) ?: "",
                node.number("estimated_minutes", 1, 1440).toInt(),
            )
        }
    require(nodes.isNotEmpty() && nodes.map { it.key }.distinct().size == nodes.size)
    val keys = nodes.map { it.key }.toSet()
    val items =
        row.list("plan_items", 1000).map {
            val item = it.obj()
            val key = item.text("node_key", 100).also { key -> require(key in keys) }
            LearningDraftItem(
                key,
                item.date("scheduled_date"),
                item.number("day_order", 1, 1000).toInt(),
                item.number("estimated_minutes", 1, 240).toInt(),
            )
        }
    require(items.isNotEmpty())
    val diagnostic =
        row.optional("diagnostic")?.obj()?.let {
            LearningDiagnostic(
                it.number("score", 0, 100).toInt(),
                it.list("strengths", 10).map { it.text(5000) },
                it.list("weaknesses", 10).map { it.text(5000) },
            )
        }
    return OnboardingPreview(
        row.text("topic", 200),
        row.text("goal", 300),
        row.text("domain", 100),
        LearningOutcome.entries.first { it.wire == row.text("outcome_type", 30) },
        row.getValue("emoji").text(10, blank = true),
        nodes,
        items,
        row.number("total_minutes", 1, 144000).toInt(),
        row.number("daily_minutes", 5, 240).toInt(),
        row.date("start_date"),
        row.date("estimated_end_date"),
        row.optional("target_date")?.text(10)?.also(::requireDate),
        row.text("effective_timezone", 100),
        row.flag("will_miss_target"),
        row.number("delay_days", 0, 3652424).toInt(),
        row.optional("risk_notice")?.text(5000),
        diagnostic,
    )
}
