import Foundation

/// One actor per backend, sharing the existing bounded atomic account IO and backup policy.
public actor FileOnboardingJournal: OnboardingJournal {
    private let storage: AccountFileStorage

    public init(directory: URL, endpointScope: String) throws {
        storage = try AccountFileStorage(directory: directory, endpointScope: endpointScope,
                                         namespace: "onboarding", maximumBytes: 4096)
    }

    public func read(ownerID: Int64) throws -> PendingOnboarding? {
        guard let bytes = try storage.read(ownerID) else { return nil }
        do {
            let row = try LearningRow(JSONSerialization.jsonObject(with: bytes))
            guard try row.number("schema", 1, 1) == 1, try row.number("owner_id", 1, 9_007_199_254_740_991) == ownerID
            else { throw OnboardingJournalFailure.corrupt }
            return try PendingOnboarding(ownerID: ownerID, runID: OnboardingID(row.text("run_id", 36)),
                                         confirmationID: OnboardingID(row.text("confirmation_id", 36)))
        } catch { throw OnboardingJournalFailure.corrupt }
    }

    public func save(_ pending: PendingOnboarding) throws {
        let previous = try read(ownerID: pending.ownerID)
        guard previous == nil || previous == pending else { throw OnboardingJournalFailure.conflict }
        if previous == pending {
            return
        }
        let bytes = try JSONSerialization.data(withJSONObject: [
            "schema": 1, "owner_id": pending.ownerID, "run_id": pending.runID.value,
            "confirmation_id": pending.confirmationID.value,
        ], options: .sortedKeys)
        try storage.write(pending.ownerID, bytes: bytes)
        guard try read(ownerID: pending.ownerID) == pending else { throw OnboardingJournalFailure.corrupt }
    }

    public func clear(_ pending: PendingOnboarding) throws {
        let previous = try read(ownerID: pending.ownerID)
        guard previous == nil || previous == pending else { throw OnboardingJournalFailure.conflict }
        if previous != nil {
            try storage.remove(pending.ownerID)
        }
        guard try read(ownerID: pending.ownerID) == nil else { throw OnboardingJournalFailure.corrupt }
    }
}
