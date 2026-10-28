import CoreFoundation
import Foundation

/// Only retained fields are decoded. Extra graph layout and provider fields stay out of UI state.
struct LearningRow {
    let values: [String: Any]
    init(_ value: Any?) throws {
        guard let values = value as? [String: Any] else { throw OnboardingFailure.invalidResponse }
        self.values = values
    }

    func optional(_ key: String) -> Any? {
        guard let value = values[key], !(value is NSNull) else { return nil }
        return value
    }

    func text(_ key: String, _ maximum: Int, blank: Bool = false) throws -> String {
        try Self.text(values[key], maximum, blank: blank)
    }

    static func text(_ value: Any?, _ maximum: Int, blank: Bool = false) throws -> String {
        guard let text = value as? String, text.unicodeScalars.count <= maximum,
              blank || !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        else {
            throw OnboardingFailure.invalidResponse
        }
        return text
    }

    func number(_ key: String, _ minimum: Int64 = 0, _ maximum: Int64 = 2_147_483_647) throws -> Int64 {
        guard let value = JSONScalar.integer(values[key], in: minimum ... maximum) else {
            throw OnboardingFailure.invalidResponse
        }
        return value
    }

    func flag(_ key: String) throws -> Bool {
        guard let value = values[key] as? NSNumber, CFGetTypeID(value) == CFBooleanGetTypeID() else {
            throw OnboardingFailure.invalidResponse
        }
        return value.boolValue
    }

    func list(_ key: String, _ maximum: Int) throws -> [Any] {
        guard let value = values[key] as? [Any], value.count <= maximum else {
            throw OnboardingFailure.invalidResponse
        }
        return value
    }

    func date(_ key: String) throws -> String {
        let value = try text(key, 10); try learningDate(value); return value
    }

    func optionalDate(_ key: String) throws -> String? {
        guard optional(key) != nil else { return nil }
        return try date(key)
    }

    func outcome() throws -> LearningOutcome {
        guard let value = try LearningOutcome(rawValue: text("outcome_type", 30)) else {
            throw OnboardingFailure.invalidResponse
        }
        return value
    }

    func form() throws -> OnboardingForm {
        guard let familiarity = try LearningFamiliarity(rawValue: text("familiarity", 30)) else {
            throw OnboardingFailure.invalidResponse
        }
        return try OnboardingForm(topic: text("topic", 200), goal: text("goal", 300), domain: text("domain", 100),
                                  outcome: outcome(), familiarity: familiarity, timezone: text("timezone", 100),
                                  dailyMinutes: Int(number("daily_minutes", 5, 240)),
                                  targetDate: optionalDate("target_date"), useDiagnostic: flag("use_diagnostic"))
    }
}

func decodeOnboarding(_ data: Data, expected: OnboardingID) throws -> OnboardingRun {
    let row = try LearningRow(JSONSerialization.jsonObject(with: data))
    guard try row.text("run_id", 36) == expected.value, try row.text("type", 30) == "onboarding",
          let status = try OnboardingStatus(rawValue: row.text("status", 40))
    else {
        throw OnboardingFailure.invalidResponse
    }
    let version = try Int(row.number("version")), processing = try row.flag("processing")
    guard !processing || [.diagnosing, .drafting].contains(status) else { throw OnboardingFailure.invalidResponse }
    let step: OnboardingStep?
    if status == .diagnosing, !processing {
        let value = try LearningRow(row.optional("step")), total = try Int(value.number("total", 1, 20))
        step = try OnboardingStep(id: value.text("step_id", 100), prompt: value.text("prompt", 2000),
                                  inputType: value.text("input_type", 30),
                                  choices: value.list("choices", 20).map { try LearningRow.text($0, 1000) },
                                  current: Int(value.number("current", 1, Int64(total))), total: total)
    } else {
        step = nil
    }
    let preview = try status == .preview ? decodePreview(row.optional("preview")) : nil
    let result: OnboardingResult?
    if status == .completed {
        let value = try LearningRow(row.optional("result"))
        result = try OnboardingResult(topicID: value.number("topic_id", 1, 9_007_199_254_740_991),
                                      planID: value.number("plan_id", 1, 9_007_199_254_740_991))
    } else {
        result = nil
    }
    let failure: OnboardingRunError?
    if let raw = row.optional("error") {
        let value = try LearningRow(raw)
        let known = ["AI_TIMEOUT", "AI_RATE_LIMITED", "AI_UPSTREAM_ERROR", "AI_REQUEST_FAILED",
                     "AI_OUTPUT_LIMIT", "AI_CONTENT_FILTERED", "STRUCTURED_OUTPUT_INVALID", "GRAPH_INVALID",
                     "AGENT_STAGE_UNKNOWN"]
        let code = try value.text("code", 80)
        failure = try OnboardingRunError(code: known.contains(code) ? code : nil, retryable: value.flag("retryable"))
    } else {
        failure = nil
    }
    return try OnboardingRun(id: expected, status: status, version: version, processing: processing,
                             input: row.optional("input").map { try LearningRow($0).form() }, step: step,
                             preview: preview, result: result, error: failure)
}

private func decodePreview(_ raw: Any?) throws -> OnboardingPreview {
    let row = try LearningRow(raw)
    let nodes = try row.list("nodes", 100).map { raw in
        let node = try LearningRow(raw)
        return try LearningDraftNode(key: node.text("key", 100), label: node.text("label", 200),
                                     detail: node.optional("sub")
                                         .map { try LearningRow.text($0, 500, blank: true) } ?? "",
                                     minutes: Int(node.number("estimated_minutes", 1, 1440)))
    }
    let keys = Set(nodes.map(\.identity))
    guard !nodes.isEmpty, keys.count == nodes.count else { throw OnboardingFailure.invalidResponse }
    let items = try row.list("plan_items", 1000).map { raw in
        let item = try LearningRow(raw), key = try item.text("node_key", 100)
        guard keys.contains(Data(key.utf8)) else { throw OnboardingFailure.invalidResponse }
        return try LearningDraftItem(nodeKey: key, date: item.date("scheduled_date"),
                                     order: Int(item.number("day_order", 1, 1000)), minutes: Int(item.number(
                                         "estimated_minutes",
                                         1,
                                         240
                                     )))
    }
    guard !items.isEmpty else { throw OnboardingFailure.invalidResponse }
    let diagnostic = try row.optional("diagnostic").map { raw in
        let value = try LearningRow(raw)
        return try LearningDiagnostic(score: Int(value.number("score", 0, 100)),
                                      strengths: value.list("strengths", 10).map { try LearningRow.text($0, 5000) },
                                      weaknesses: value.list("weaknesses", 10).map { try LearningRow.text($0, 5000) })
    }
    return try OnboardingPreview(
        topic: row.text("topic", 200),
        goal: row.text("goal", 300),
        domain: row.text("domain", 100),
        outcome: row.outcome(),
        emoji: row.text("emoji", 10, blank: true),
        nodes: nodes,
        items: items,
        totalMinutes: Int(row.number("total_minutes", 1, 144_000)),
        dailyMinutes: Int(row.number("daily_minutes", 5, 240)),
        startDate: row.date("start_date"),
        endDate: row.date("estimated_end_date"),
        targetDate: row.optionalDate("target_date"),
        timezone: row.text("effective_timezone", 100),
        willMissTarget: row.flag("will_miss_target"),
        delayDays: Int(row.number("delay_days", 0, 3_652_424)),
        riskNotice: row.optional("risk_notice").map { try LearningRow.text($0, 5000) },
        diagnostic: diagnostic
    )
}
