import Foundation

public protocol OnboardingGateway: Sendable {
    func start(token: String, id: OnboardingID, form: OnboardingForm, model: String?) async throws -> OnboardingRun
    func read(token: String, id: OnboardingID) async throws -> OnboardingRun
    func answer(token: String, id: OnboardingID, version: Int, stepID: String, answer: String) async throws
        -> OnboardingRun
    func revise(token: String, id: OnboardingID, version: Int, goal: String, dailyMinutes: Int,
                targetDate: String?, timezone: String) async throws -> OnboardingRun
    func confirm(token: String, id: OnboardingID, version: Int, requestID: String) async throws -> OnboardingRun
    func cancel(token: String, id: OnboardingID) async throws -> OnboardingRun
    func retry(token: String, id: OnboardingID, version: Int) async throws -> OnboardingRun
}

/// Uses bounded authenticated transport without mutation retries; recovery reads the same ID.
public struct OnboardingAPI: OnboardingGateway {
    private let transport: HTTPTransport
    public init(transport: HTTPTransport) {
        self.transport = transport
    }

    public func start(token: String, id: OnboardingID, form: OnboardingForm,
                      model: String? = nil) async throws -> OnboardingRun
    {
        if let model {
            try learningText(model, maximum: 100)
        }
        var body = form.wire
        body["run_id"] = id.value
        if let model {
            body["model"] = model
        }
        let data = try await transport.request(method: "POST", path: "api/agent/onboarding", bearer: token,
                                               json: JSONSerialization.data(withJSONObject: body))
        return try OnboardingRun.decode(data, expected: id)
    }

    public func read(token: String, id: OnboardingID) async throws -> OnboardingRun {
        try await request("GET", token: token, id: id)
    }

    public func answer(token: String, id: OnboardingID, version: Int,
                       stepID: String, answer: String) async throws -> OnboardingRun
    {
        try validVersion(version); try learningText(stepID, maximum: 100); try learningText(answer, maximum: 5000)
        return try await request("POST", token: token, id: id, suffix: "/answers", body: [
            "version": version, "step_id": stepID, "answer": answer.trimmingCharacters(in: .whitespacesAndNewlines),
        ])
    }

    public func revise(token: String, id: OnboardingID, version: Int, goal: String, dailyMinutes: Int,
                       targetDate: String?, timezone: String) async throws -> OnboardingRun
    {
        try validVersion(version); try learningText(goal, maximum: 300); try learningText(timezone, maximum: 100)
        guard (5 ... 240).contains(dailyMinutes) else { throw OnboardingFailure.invalidInput }
        if let targetDate {
            try learningDate(targetDate)
        }
        return try await request("PATCH", token: token, id: id, body: [
            "version": version, "goal": goal.trimmingCharacters(in: .whitespacesAndNewlines),
            "daily_minutes": dailyMinutes, "target_date": targetDate as Any? ?? NSNull(),
            "timezone": timezone.trimmingCharacters(in: .whitespacesAndNewlines),
        ])
    }

    public func confirm(token: String, id: OnboardingID, version: Int,
                        requestID: String) async throws -> OnboardingRun
    {
        try validVersion(version); try learningText(requestID, maximum: 100)
        return try await request(
            "POST",
            token: token,
            id: id,
            suffix: "/confirm",
            body: ["version": version, "request_id": requestID]
        )
    }

    public func cancel(token: String, id: OnboardingID) async throws -> OnboardingRun {
        try await request("POST", token: token, id: id, suffix: "/cancel")
    }

    public func retry(token: String, id: OnboardingID, version: Int) async throws -> OnboardingRun {
        try validVersion(version)
        return try await request("POST", token: token, id: id, suffix: "/retry", body: ["version": version])
    }

    private func validVersion(_ value: Int) throws {
        guard (0 ... 2_147_483_647).contains(value) else { throw OnboardingFailure.invalidInput }
    }

    private func request(_ method: String, token: String, id: OnboardingID, suffix: String = "",
                         body: [String: Any]? = nil) async throws -> OnboardingRun
    {
        let data = try await transport.request(
            method: method,
            path: "api/agent/runs/\(id.value)\(suffix)",
            bearer: token,
            json: body.map { try JSONSerialization.data(withJSONObject: $0) }
        )
        return try OnboardingRun.decode(data, expected: id)
    }
}
