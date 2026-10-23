import Foundation
import Markdown

/// Pure projection; MarkdownRenderer performs it away from the main actor.
public enum MarkdownParser {
    public static func parse(_ source: String) -> MarkdownDocument {
        guard MarkdownBudget.accepts(source) else { return plainMarkdown(source) }
        do {
            let document = Document(parsing: source, options: [.disableSmartOpts])
            return try MarkdownBlockProjection().document(document)
        } catch { return plainMarkdown(source) }
    }
}

private final class MarkdownBlockProjection {
    private let budget = MarkdownBudget()
    private var blocks: [MarkdownBlock] = []
    private var inline: MarkdownInlineProjection {
        MarkdownInlineProjection(budget: budget)
    }

    func document(_ root: Document) throws -> MarkdownDocument {
        for child in root.children {
            try visit(child, quote: 0, indent: 0, depth: 0)
        }
        return MarkdownDocument(blocks)
    }

    private func visit(_ node: any Markup, quote: Int, indent: Int, depth: Int) throws {
        try budget.visit(depth)
        switch node {
        case is Paragraph: try add(.text(inline.runs(node)), quote: quote, indent: indent)
        case let heading as Heading: try add(
                .text(inline.runs(node), heading: heading.level),
                quote: quote,
                indent: indent
            )
        case let code as CodeBlock:
            try budget.literal(code.code)
            let language = String((code.language ?? "").split(whereSeparator: \.isWhitespace).first?.prefix(64) ?? "")
            try add(.code(code.code, language: language), quote: quote, indent: indent)
        case let html as HTMLBlock:
            try budget.literal(html.rawHTML)
            try add(.text([MarkdownRun(html.rawHTML)]), quote: quote, indent: indent)
        case is ThematicBreak: try add(.rule, quote: quote, indent: indent)
        case is BlockQuote:
            for child in node.children {
                try visit(child, quote: quote + 1, indent: indent, depth: depth + 1)
            }
        case is UnorderedList, is OrderedList: try list(node, quote: quote, indent: indent, depth: depth)
        case let table as Table: try projectTable(table, quote: quote, indent: indent)
        default:
            for child in node.children {
                try visit(child, quote: quote, indent: indent, depth: depth + 1)
            }
        }
    }

    private func list(_ node: any Markup, quote: Int, indent: Int, depth: Int) throws {
        var number = (node as? OrderedList)?.startIndex ?? 1
        for item in node.children {
            try budget.visit(depth + 1)
            let first = blocks.count
            let marker: String
            if let checked = (item as? ListItem)?.checkbox {
                marker = checked == .checked ? "☑" : "☐"
            } else if node is OrderedList {
                marker = "\(number)."; number += 1
            } else {
                marker = "•"
            }
            for child in item.children {
                try visit(child, quote: quote, indent: indent + 1, depth: depth + 2)
            }
            if blocks.count == first {
                try add(.text([]), quote: quote, indent: indent + 1)
            }
            if blocks[first].marker != nil {
                guard blocks.count < 512 else { throw MarkdownLimit.exceeded }
                blocks.insert(MarkdownBlock(.text([]), quote: quote, indent: indent + 1), at: first)
            }
            blocks[first].marker = marker
        }
    }

    private func projectTable(_ table: Table, quote: Int, indent: Int) throws {
        let cells = [Array(table.head.children)] + table.body.children.map { Array($0.children) }
        guard table.columnAlignments.count <= 32, cells.reduce(0, { $0 + $1.count }) <= 2048,
              cells.allSatisfy({ $0.count == table.columnAlignments.count })
        else {
            throw MarkdownLimit.exceeded
        }
        let alignments: [MarkdownAlignment] = table.columnAlignments.map {
            switch $0 {
            case .center: .center
            case .right: .right
            default: .left
            }
        }
        let rows = try cells.map { row in try row.map { try budget.visit(0); return try inline.runs($0) } }
        try add(.table(MarkdownTable(alignments: alignments, rows: rows)), quote: quote, indent: indent)
    }

    private func add(_ content: MarkdownContent, quote: Int, indent: Int) throws {
        guard blocks.count < 512 else { throw MarkdownLimit.exceeded }
        blocks.append(MarkdownBlock(content, quote: quote, indent: indent))
    }
}
