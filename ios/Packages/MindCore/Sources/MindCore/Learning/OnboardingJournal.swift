import Foundation

/// Stable identifiers only; allocated and saved before the initial request.
public struct PendingOnboarding: Equatable, Sendable {
    public let ownerID: Int64
    public let runID: OnboardingID
    public let confirmationID: OnboardingID

    public init(ownerID: Int64, runID: OnboardingID, confirmationID: OnboardingID) throws {
        guard (1 ... 9_007_199_254_740_991).contains(ownerID) else { throw OnboardingFailure.invalidInput }
        self.ownerID = ownerID; self.runID = runID; self.confirmationID = confirmationID
    }
}

public protocol OnboardingJournal: Sendable {
    func read(ownerID: Int64) async throws -> PendingOnboarding?
    func save(_ pending: PendingOnboarding) async throws
    func clear(_ pending: PendingOnboarding) async throws
}

public enum OnboardingJournalFailure: Error { case corrupt, conflict }
