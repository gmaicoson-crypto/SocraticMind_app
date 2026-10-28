import Foundation

public enum LearningOutcome: String, Sendable {
    case concept, procedure, analysis, expression, creation, mixed
}

public enum LearningFamiliarity: String, Sendable {
    case new, beginner, intermediate, advanced
}

public enum OnboardingFailure: Error, Equatable { case invalidInput, invalidResponse }

public struct OnboardingForm: Equatable, Sendable {
    public let topic: String
    public let goal: String
    public let domain: String
    public let outcome: LearningOutcome
    public let familiarity: LearningFamiliarity
    public let timezone: String
    public let dailyMinutes: Int
    public let targetDate: String?
    public let useDiagnostic: Bool

    public init(topic: String, goal: String, domain: String, outcome: LearningOutcome,
                familiarity: LearningFamiliarity, timezone: String, dailyMinutes: Int = 30,
                targetDate: String? = nil, useDiagnostic: Bool = true) throws
    {
        for (value, maximum) in [(topic, 200), (goal, 300), (domain, 100), (timezone, 100)] {
            try learningText(value, maximum: maximum)
        }
        guard (5 ... 240).contains(dailyMinutes) else { throw OnboardingFailure.invalidInput }
        if let targetDate {
            try learningDate(targetDate)
        }
        self.topic = topic; self.goal = goal; self.domain = domain
        self.outcome = outcome; self.familiarity = familiarity; self.timezone = timezone
        self.dailyMinutes = dailyMinutes; self.targetDate = targetDate; self.useDiagnostic = useDiagnostic
    }

    var wire: [String: Any] {
        ["topic": topic.trimmingCharacters(in: .whitespacesAndNewlines),
         "goal": goal.trimmingCharacters(in: .whitespacesAndNewlines),
         "domain": domain.trimmingCharacters(in: .whitespacesAndNewlines),
         "outcome_type": outcome.rawValue, "familiarity": familiarity.rawValue,
         "timezone": timezone.trimmingCharacters(in: .whitespacesAndNewlines),
         "daily_minutes": dailyMinutes, "target_date": targetDate as Any? ?? NSNull(),
         "use_diagnostic": useDiagnostic]
    }
}

public struct OnboardingID: Hashable, Sendable {
    public let value: String
    public init(_ value: String) throws {
        guard value.utf8.count == 36,
              value.range(of: "^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
                          options: .regularExpression) != nil else { throw OnboardingFailure.invalidInput }
        self.value = value
    }

    public static func create() -> OnboardingID {
        OnboardingID(uuid: UUID())
    }

    private init(uuid: UUID) {
        value = uuid.uuidString.lowercased()
    }
}

func learningText(_ value: String, maximum: Int) throws {
    guard !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
          value.unicodeScalars.count <= maximum else { throw OnboardingFailure.invalidInput }
}

func learningDate(_ value: String) throws {
    guard value.utf8.count == 10,
          value.range(of: "^[0-9]{4}-[0-9]{2}-[0-9]{2}$", options: .regularExpression) != nil
    else {
        throw OnboardingFailure.invalidInput
    }
    let parts = value.split(separator: "-").compactMap { Int($0) }
    guard parts.count == 3, (1 ... 9999).contains(parts[0]), (1 ... 12).contains(parts[1]) else {
        throw OnboardingFailure.invalidInput
    }
    let leap = parts[0].isMultiple(of: 400) || (parts[0].isMultiple(of: 4) && !parts[0].isMultiple(of: 100))
    let days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    guard (1 ... days[parts[1] - 1]).contains(parts[2]) else { throw OnboardingFailure.invalidInput }
}
