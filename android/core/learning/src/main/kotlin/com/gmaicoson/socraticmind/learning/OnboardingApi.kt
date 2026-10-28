package com.gmaicoson.socraticmind.learning

import com.gmaicoson.socraticmind.network.HttpTransport
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

interface OnboardingGateway {
    suspend fun start(
        token: String,
        id: OnboardingID,
        form: OnboardingForm,
        model: String? = null,
    ): OnboardingRun

    suspend fun read(
        token: String,
        id: OnboardingID,
    ): OnboardingRun

    suspend fun answer(
        token: String,
        id: OnboardingID,
        version: Int,
        stepId: String,
        answer: String,
    ): OnboardingRun

    suspend fun revise(
        token: String,
        id: OnboardingID,
        version: Int,
        goal: String,
        dailyMinutes: Int,
        targetDate: String?,
        timezone: String,
    ): OnboardingRun

    suspend fun confirm(
        token: String,
        id: OnboardingID,
        version: Int,
        requestId: String,
    ): OnboardingRun

    suspend fun cancel(
        token: String,
        id: OnboardingID,
    ): OnboardingRun

    suspend fun retry(
        token: String,
        id: OnboardingID,
        version: Int,
    ): OnboardingRun
}

/** No mutation retries. A lost response is reconciled by reading the same persisted ID. */
class OnboardingApi(
    private val transport: HttpTransport,
) : OnboardingGateway {
    override suspend fun start(
        token: String,
        id: OnboardingID,
        form: OnboardingForm,
        model: String?,
    ): OnboardingRun {
        model?.let { requireText(it, 100) }
        val body =
            buildJsonObject {
                form.json().forEach { (key, value) -> put(key, value) }
                put("run_id", id.value)
                model?.let { put("model", it) }
            }
        return decode(transport.request("POST", "api/agent/onboarding", bearer = token, json = body), id)
    }

    override suspend fun read(
        token: String,
        id: OnboardingID,
    ) = request("GET", token, id)

    override suspend fun answer(
        token: String,
        id: OnboardingID,
        version: Int,
        stepId: String,
        answer: String,
    ): OnboardingRun {
        require(version >= 0)
        requireText(stepId, 100)
        requireText(answer, 5000)
        return request(
            "POST",
            token,
            id,
            "/answers",
            buildJsonObject {
                put("version", version)
                put("step_id", stepId)
                put("answer", answer.trim())
            },
        )
    }

    override suspend fun revise(
        token: String,
        id: OnboardingID,
        version: Int,
        goal: String,
        dailyMinutes: Int,
        targetDate: String?,
        timezone: String,
    ): OnboardingRun {
        require(version >= 0 && dailyMinutes in 5..240)
        requireText(goal, 300)
        requireText(timezone, 100)
        targetDate?.let(::requireDate)
        return request(
            "PATCH",
            token,
            id,
            json =
                buildJsonObject {
                    put("version", version)
                    put("goal", goal.trim())
                    put("daily_minutes", dailyMinutes)
                    put("target_date", targetDate)
                    put("timezone", timezone.trim())
                },
        )
    }

    override suspend fun confirm(
        token: String,
        id: OnboardingID,
        version: Int,
        requestId: String,
    ): OnboardingRun {
        require(version >= 0)
        requireText(requestId, 100)
        return request(
            "POST",
            token,
            id,
            "/confirm",
            buildJsonObject {
                put("version", version)
                put("request_id", requestId)
            },
        )
    }

    override suspend fun cancel(
        token: String,
        id: OnboardingID,
    ) = request("POST", token, id, "/cancel")

    override suspend fun retry(
        token: String,
        id: OnboardingID,
        version: Int,
    ): OnboardingRun {
        require(version >= 0)
        return request("POST", token, id, "/retry", buildJsonObject { put("version", version) })
    }

    private suspend fun request(
        method: String,
        token: String,
        id: OnboardingID,
        suffix: String = "",
        json: JsonObject? = null,
    ): OnboardingRun =
        decode(transport.request(method, "api/agent/runs/${id.value}$suffix", bearer = token, json = json), id)

    private fun decode(
        value: kotlinx.serialization.json.JsonElement,
        id: OnboardingID,
    ) = OnboardingRun.decode(value, id)
}
