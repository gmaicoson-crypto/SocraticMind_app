package com.gmaicoson.socraticmind.learning

import kotlinx.serialization.json.JsonElement

enum class OnboardingStatus(
    val wire: String,
) {
    COLLECTING("collecting"),
    DIAGNOSING("diagnosing"),
    DRAFTING("drafting"),
    PREVIEW("awaiting_confirmation"),
    COMPLETED("completed"),
    FAILED("failed"),
    CANCELLED("cancelled"),
}

data class OnboardingStep(
    val id: String,
    val prompt: String,
    val inputType: String,
    val choices: List<String>,
    val current: Int,
    val total: Int,
)

data class LearningDraftNode(
    val key: String,
    val label: String,
    val detail: String,
    val minutes: Int,
)

data class LearningDraftItem(
    val nodeKey: String,
    val date: String,
    val order: Int,
    val minutes: Int,
)

data class LearningDiagnostic(
    val score: Int,
    val strengths: List<String>,
    val weaknesses: List<String>,
)

data class OnboardingPreview(
    val topic: String,
    val goal: String,
    val domain: String,
    val outcome: LearningOutcome,
    val emoji: String,
    val nodes: List<LearningDraftNode>,
    val items: List<LearningDraftItem>,
    val totalMinutes: Int,
    val dailyMinutes: Int,
    val startDate: String,
    val endDate: String,
    val targetDate: String?,
    val timezone: String,
    val willMissTarget: Boolean,
    val delayDays: Int,
    val riskNotice: String?,
    val diagnostic: LearningDiagnostic?,
)

data class OnboardingResult(
    val topicId: Long,
    val planId: Long,
)

/** Unknown provider codes stay generic; upstream text is never a UI error message. */
data class OnboardingRunError(
    val code: String?,
    val retryable: Boolean,
)

data class OnboardingRun(
    val id: OnboardingID,
    val status: OnboardingStatus,
    val version: Int,
    val processing: Boolean,
    val input: OnboardingForm?,
    val step: OnboardingStep?,
    val preview: OnboardingPreview?,
    val result: OnboardingResult?,
    val error: OnboardingRunError?,
) {
    companion object {
        fun decode(
            value: JsonElement,
            expected: OnboardingID,
        ): OnboardingRun = decodeOnboarding(value, expected)
    }
}
