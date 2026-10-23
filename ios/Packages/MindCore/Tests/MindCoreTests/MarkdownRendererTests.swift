import Foundation
@testable import MindCore
import Testing

struct MarkdownRendererTests {
    @Test
    func reusesRecentEntriesAndEvictsLeastRecentlyUsed() async throws {
        let calls = MarkdownCalls()
        let renderer = MarkdownRenderer(maxEntries: 2, maxSourceBytes: 1024, parse: calls.parse)
        #expect(try await renderer.render("a") == MarkdownParser.parse("a"))
        for source in ["b", "a", "c", "b"] {
            _ = try await renderer.render(source)
        }
        #expect(calls.count("a") == 1)
        #expect(calls.count("b") == 2)
        #expect(calls.count("c") == 1)
    }

    @Test
    func appliesUtf8BudgetAndDoesNotCacheOversizedMessages() async throws {
        let calls = MarkdownCalls()
        let renderer = MarkdownRenderer(maxEntries: 8, maxSourceBytes: 6, parse: calls.parse)
        for source in ["甲", "乙", "甲", "丙", "超出预算", "超出预算", "甲", "乙"] {
            _ = try await renderer.render(source)
        }
        #expect(calls.count("甲") == 1)
        #expect(calls.count("乙") == 2)
        #expect(calls.count("超出预算") == 2)
    }

    @Test
    func clearRejectsLateResultsAndInvalidatesPreviouslyCachedContent() async throws {
        let calls = MarkdownCalls(gatedSource: "late")
        let renderer = MarkdownRenderer(maxEntries: 2, maxSourceBytes: 1024, parse: calls.parse)
        _ = try await renderer.render("cached")
        let stale = Task { try await renderer.render("late") }
        defer { calls.release.signal(); stale.cancel() }
        try await calls.awaitStarted()
        await renderer.clear()
        calls.release.signal()
        do { _ = try await stale.value; Issue.record("Cleared content must not be returned") }
        catch is CancellationError { /* Expected even if the library ignores cancellation. */ }
        _ = try await renderer.render("cached")
        _ = try await renderer.render("late")
        #expect(calls.count("cached") == 2)
        #expect(calls.count("late") == 2)
    }

    @Test
    func cancelledParserCannotPopulateTheCache() async throws {
        let calls = MarkdownCalls(gatedSource: "cancelled")
        let renderer = MarkdownRenderer(maxEntries: 2, maxSourceBytes: 1024, parse: calls.parse)
        let pending = Task { try await renderer.render("cancelled") }
        defer { calls.release.signal(); pending.cancel() }
        try await calls.awaitStarted()
        pending.cancel(); calls.release.signal()
        do { _ = try await pending.value; Issue.record("Cancellation must propagate") }
        catch is CancellationError { /* Expected. */ }
        _ = try await renderer.render("cancelled")
        #expect(calls.count("cancelled") == 2)
    }

    @Test @MainActor
    func independentScopesNeverShareCachedContentAndParsingRunsOffTheCaller() async throws {
        let calls = MarkdownCalls()
        let parse: @Sendable (String) -> MarkdownDocument = { source in
            #expect(!Thread.isMainThread)
            return calls.parse(source)
        }
        let first = MarkdownRenderer(maxEntries: 2, maxSourceBytes: 1024, parse: parse)
        let second = MarkdownRenderer(maxEntries: 2, maxSourceBytes: 1024, parse: parse)
        _ = try await first.render("same")
        _ = try await second.render("same")
        _ = try await first.render("same")
        #expect(calls.count("same") == 2)
    }
}

/// All mutable test state is behind NSLock; the gate blocks only the background parsing worker.
private final class MarkdownCalls: @unchecked Sendable {
    private let lock = NSLock()
    private var counts: [String: Int] = [:]
    private var started = false
    private let gatedSource: String?
    let release = DispatchSemaphore(value: 0)

    init(gatedSource: String? = nil) {
        self.gatedSource = gatedSource
    }

    func count(_ source: String) -> Int {
        lock.withLock { counts[source] ?? 0 }
    }

    func parse(_ source: String) -> MarkdownDocument {
        let gated = lock.withLock {
            let first = counts[source] == nil
            counts[source, default: 0] += 1
            if source == gatedSource, first {
                started = true; return true
            }
            return false
        }
        if gated {
            #expect(release.wait(timeout: .now() + 3) == .success)
        }
        return MarkdownParser.parse(source)
    }

    func awaitStarted() async throws {
        let deadline = ContinuousClock.now.advanced(by: .seconds(2))
        while !lock.withLock({ started }) {
            guard ContinuousClock.now < deadline else { throw SessionTestError.timeout }
            try await Task.sleep(for: .milliseconds(1))
        }
    }
}
