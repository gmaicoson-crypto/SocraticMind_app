import Foundation

public struct OnboardingAccount: Equatable, Sendable {
    public let ownerID: Int64
    public let revision: UInt64
    static func from(_ value: SessionState) -> OnboardingAccount? {
        guard case let .signedIn(user, revision) = value else { return nil }
        return OnboardingAccount(ownerID: user.id, revision: revision)
    }
}

public enum OnboardingIssue: Sendable { case storage, request, conflict, notFound }

public struct OnboardingState: Equatable, Sendable {
    public internal(set) var account: OnboardingAccount?
    public internal(set) var ready = false
    public internal(set) var busy = false
    public internal(set) var pending: PendingOnboarding?
    public internal(set) var run: OnboardingRun?
    public internal(set) var needsRefresh = false
    public internal(set) var issue: OnboardingIssue?
    public internal(set) var receipt: OnboardingResult?
    public var canStart: Bool {
        account != nil && ready && !busy && !needsRefresh && pending == nil && receipt == nil
    }

    public var canMutate: Bool {
        ready && !busy && pending != nil && run != nil && !needsRefresh && run?.processing == false
    }

    public var canAnswer: Bool {
        canMutate && run?.status == .diagnosing && run?.step != nil
    }

    public var canRevise: Bool {
        canMutate && run?.status == .preview
    }

    public var canConfirm: Bool {
        canRevise
    }

    public var canRetry: Bool {
        canMutate && run?.status == .failed && run?.error?.retryable == true
    }

    public var canCancel: Bool {
        pending != nil && run?.status != .completed && run?.status != .cancelled
    }
}
