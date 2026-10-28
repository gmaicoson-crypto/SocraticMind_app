package com.gmaicoson.socraticmind.learning

import com.gmaicoson.socraticmind.auth.SessionState

data class OnboardingAccount(
    val ownerId: Long,
    val revision: Long,
) {
    companion object {
        fun from(value: SessionState): OnboardingAccount? =
            (value as? SessionState.SignedIn)?.let { OnboardingAccount(it.user.id, it.revision) }
    }
}

enum class OnboardingIssue { STORAGE, REQUEST, CONFLICT, NOT_FOUND }

data class OnboardingState(
    val account: OnboardingAccount? = null,
    val ready: Boolean = false,
    val busy: Boolean = false,
    val pending: PendingOnboarding? = null,
    val run: OnboardingRun? = null,
    val needsRefresh: Boolean = false,
    val issue: OnboardingIssue? = null,
    val receipt: OnboardingResult? = null,
) {
    val canStart: Boolean get() =
        account != null && ready && !busy && !needsRefresh && pending == null &&
            receipt == null
    val canMutate: Boolean get() = ready && !busy && pending != null && run != null && !needsRefresh && !run.processing
    val canAnswer: Boolean get() = canMutate && run?.status == OnboardingStatus.DIAGNOSING && run.step != null
    val canRevise: Boolean get() = canMutate && run?.status == OnboardingStatus.PREVIEW
    val canConfirm: Boolean get() = canRevise
    val canRetry: Boolean get() = canMutate && run?.status == OnboardingStatus.FAILED && run.error?.retryable == true
    val canCancel: Boolean get() =
        pending != null &&
            run?.status !in listOf(OnboardingStatus.COMPLETED, OnboardingStatus.CANCELLED)
}
