package com.gmaicoson.socraticmind.learning

/** Persisted before creation. Contains identifiers only, never form/answer text or credentials. */
data class PendingOnboarding(
    val ownerId: Long,
    val runId: OnboardingID,
    val confirmationId: OnboardingID,
) {
    init {
        require(ownerId in 1..9_007_199_254_740_991)
    }
}

interface OnboardingJournal {
    suspend fun read(ownerId: Long): PendingOnboarding?

    suspend fun save(pending: PendingOnboarding)

    suspend fun clear(pending: PendingOnboarding)
}
