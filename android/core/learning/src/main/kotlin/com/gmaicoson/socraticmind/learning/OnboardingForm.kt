package com.gmaicoson.socraticmind.learning

import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.time.LocalDate
import java.util.UUID

enum class LearningOutcome(
    val wire: String,
) {
    CONCEPT("concept"),
    PROCEDURE("procedure"),
    ANALYSIS("analysis"),
    EXPRESSION("expression"),
    CREATION("creation"),
    MIXED("mixed"),
}

enum class LearningFamiliarity(
    val wire: String,
) {
    NEW("new"),
    BEGINNER("beginner"),
    INTERMEDIATE("intermediate"),
    ADVANCED("advanced"),
}

/** Validated submission values; editable text belongs to the form state, not transport. */
data class OnboardingForm(
    val topic: String,
    val goal: String,
    val domain: String,
    val outcome: LearningOutcome,
    val familiarity: LearningFamiliarity,
    val timezone: String,
    val dailyMinutes: Int = 30,
    val targetDate: String? = null,
    val useDiagnostic: Boolean = true,
) {
    init {
        requireText(topic, 200)
        requireText(goal, 300)
        requireText(domain, 100)
        requireText(timezone, 100)
        require(dailyMinutes in 5..240)
        targetDate?.let(::requireDate)
    }

    internal fun json(): JsonObject =
        buildJsonObject {
            put("topic", topic.trim())
            put("goal", goal.trim())
            put("domain", domain.trim())
            put("outcome_type", outcome.wire)
            put("familiarity", familiarity.wire)
            put("timezone", timezone.trim())
            put("daily_minutes", dailyMinutes)
            put("target_date", targetDate?.let { kotlinx.serialization.json.JsonPrimitive(it) } ?: JsonNull)
            put("use_diagnostic", useDiagnostic)
        }
}

data class OnboardingID(
    val value: String,
) {
    init {
        require(value.matches(Regex("[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")))
    }

    companion object {
        fun create() = OnboardingID(UUID.randomUUID().toString())
    }
}

internal fun requireText(
    value: String,
    maximum: Int,
) {
    require(value.isNotBlank() && value.codePointCount(0, value.length) <= maximum)
}

internal fun requireDate(value: String) {
    require(value.matches(Regex("[0-9]{4}-[0-9]{2}-[0-9]{2}")))
    require(LocalDate.parse(value).year in 1..9999)
}
