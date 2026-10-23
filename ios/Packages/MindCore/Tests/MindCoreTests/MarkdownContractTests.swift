import Foundation
@testable import MindCore
import Testing

struct MarkdownContractTests {
    @Test
    func projectsSharedFormattingAndLiteralSafetyCases() throws {
        let fixture = try fixture()
        for item in fixture.cases {
            let result = MarkdownParser.parse(item.source)
            #expect(!result.plainFallback, "\(item.id)")
            let actual = try JSONDecoder().decode(ChatJSONValue.self, from: JSONSerialization.data(
                withJSONObject: result.blocks.map(snapshot)
            ))
            #expect(actual == item.blocks, "\(item.id)")
        }
    }

    @Test
    func appliesTheSameWebLinkPolicyOnBothPlatforms() throws {
        for item in try fixture().links {
            #expect(MarkdownLink.safe(item.input) == item.safe, "\(item.input)")
        }
    }

    @Test
    func boundedFallbackPreservesEveryScalarAndNewline() {
        let wideRow = "|" + Array(repeating: "a", count: 33).joined(separator: "|") + "|\n"
        let wideDivider = "|" + Array(repeating: "---", count: 33).joined(separator: "|") + "|\n"
        let sources = [
            String(repeating: "中文🙂é\n", count: 20000),
            "```\n" + String(repeating: "x", count: 16 * 1024 + 1) + "\n```",
            String(repeating: "*", count: 300) + "保留",
            String(repeating: "> ", count: 40) + "深层",
            String(repeating: "段落\n\n", count: 513),
            wideRow + wideDivider + wideRow,
            "|a|b|c|\n|---|---|---|\n" + String(repeating: "|x|y|z|\n", count: 684),
        ]
        for (index, source) in sources.enumerated() {
            let result = MarkdownParser.parse(source)
            #expect(result.plainFallback, "case \(index)")
            let chunks = result.blocks.compactMap { block -> String? in
                guard case let .text(runs, _) = block.content else { return nil }
                return runs.map(\.text).joined()
            }
            #expect(chunks.joined() == source, "case \(index)")
            #expect(chunks.allSatisfy { $0.unicodeScalars.count <= 2048 })
        }
    }

    private func fixture() throws -> Fixture {
        var root = URL(fileURLWithPath: #filePath)
        for _ in 0 ..< 6 {
            root.deleteLastPathComponent()
        }
        return try JSONDecoder().decode(Fixture.self, from: Data(contentsOf:
            root.appendingPathComponent("contracts/fixtures/message-markdown.json")))
    }

    private struct Fixture: Decodable {
        let cases: [Case]
        let links: [Link]
        struct Case: Decodable { let id: String; let source: String; let blocks: ChatJSONValue }
        struct Link: Decodable { let input: String; let safe: String? }
    }

    private func snapshot(_ block: MarkdownBlock) -> [String: Any] {
        var value: [String: Any] = [:]
        if block.quoteDepth != 0 {
            value["quote"] = block.quoteDepth
        }
        if block.indent != 0 {
            value["indent"] = block.indent
        }
        if let marker = block.marker {
            value["marker"] = marker
        }
        switch block.content {
        case let .text(runs, heading):
            value["type"] = "text"; value["runs"] = runs.map(snapshotRun)
            if heading != 0 {
                value["heading"] = heading
            }
        case let .code(text, language):
            value["type"] = "code"; value["text"] = text; value["language"] = language
        case let .table(table):
            value["type"] = "table"; value["alignments"] = table.alignments.map(\.rawValue)
            value["rows"] = table.rows.map { $0.map { $0.map(snapshotRun) } }
        case .rule: value["type"] = "rule"
        }
        return value
    }

    private func snapshotRun(_ run: MarkdownRun) -> [String: Any] {
        var value: [String: Any] = ["text": run.text]
        if run.style.bold {
            value["bold"] = true
        }
        if run.style.italic {
            value["italic"] = true
        }
        if run.style.strike {
            value["strike"] = true
        }
        if run.style.code {
            value["code"] = true
        }
        if let link = run.link {
            value["link"] = link
        }
        return value
    }
}
