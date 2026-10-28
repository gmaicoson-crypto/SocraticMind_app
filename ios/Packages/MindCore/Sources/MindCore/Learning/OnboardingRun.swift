import Foundation

public enum OnboardingStatus: String, Sendable {
    case collecting, diagnosing, drafting, completed, failed, cancelled
    case preview = "awaiting_confirmation"
}

public struct OnboardingStep: Equatable, Sendable {
    public let id: String
    public let prompt: String
    public let inputType: String
    public let choices: [String]
    public let current: Int
    public let total: Int
}

public struct LearningDraftNode: Equatable, Sendable {
    public let key: String
    public let label: String
    public let detail: String
    public let minutes: Int
    public var identity: Data {
        Data(key.utf8)
    }
}

public struct LearningDraftItem: Equatable, Sendable {
    public let nodeKey: String
    public let date: String
    public let order: Int
    public let minutes: Int
}

public struct LearningDiagnostic: Equatable, Sendable {
    public let score: Int
    public let strengths: [String]
    public let weaknesses: [String]
}

public struct OnboardingPreview: Equatable, Sendable {
    public let topic: String
    public let goal: String
    public let domain: String
    public let outcome: LearningOutcome
    public let emoji: String
    public let nodes: [LearningDraftNode]
    public let items: [LearningDraftItem]
    public let totalMinutes: Int
    public let dailyMinutes: Int
    public let startDate: String
    public let endDate: String
    public let targetDate: String?
    public let timezone: String
    public let willMissTarget: Bool
    public let delayDays: Int
    public let riskNotice: String?
    public let diagnostic: LearningDiagnostic?
}

public struct OnboardingResult: Equatable, Sendable {
    public let topicID: Int64
    public let planID: Int64
}

public struct OnboardingRunError: Equatable, Sendable {
    public let code: String?
    public let retryable: Bool
}

public struct OnboardingRun: Equatable, Sendable {
    public let id: OnboardingID
    public let status: OnboardingStatus
    public let version: Int
    public let processing: Bool
    public let input: OnboardingForm?
    public let step: OnboardingStep?
    public let preview: OnboardingPreview?
    public let result: OnboardingResult?
    public let error: OnboardingRunError?

    public static func decode(_ data: Data, expected: OnboardingID) throws -> OnboardingRun {
        guard data.count <= 1_048_576 else { throw OnboardingFailure.invalidResponse }
        do { return try decodeOnboarding(data, expected: expected) }
        catch { throw OnboardingFailure.invalidResponse }
    }
}
