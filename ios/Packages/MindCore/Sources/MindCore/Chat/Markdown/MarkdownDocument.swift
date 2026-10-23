import Foundation

public struct MarkdownStyle: Equatable, Sendable {
    public internal(set) var bold = false
    public internal(set) var italic = false
    public internal(set) var strike = false
    public internal(set) var code = false
}

public struct MarkdownRun: Equatable, Sendable {
    public let text: String
    public let style: MarkdownStyle
    public let link: String?

    init(_ text: String, style: MarkdownStyle = MarkdownStyle(), link: String? = nil) {
        self.text = text; self.style = style; self.link = link
    }
}

public enum MarkdownAlignment: String, Sendable { case left, center, right }

public struct MarkdownTable: Equatable, Sendable {
    public let alignments: [MarkdownAlignment]
    public let rows: [[[MarkdownRun]]]
}

public enum MarkdownContent: Equatable, Sendable {
    case text([MarkdownRun], heading: Int = 0)
    case code(String, language: String)
    case table(MarkdownTable)
    case rule
}

/// Flatten containers for lazy views; only the first child block carries its list marker.
public struct MarkdownBlock: Equatable, Sendable {
    public let content: MarkdownContent
    public let quoteDepth: Int
    public let indent: Int
    public internal(set) var marker: String?

    init(_ content: MarkdownContent, quote: Int = 0, indent: Int = 0) {
        self.content = content; quoteDepth = quote; self.indent = indent
    }
}

public struct MarkdownDocument: Equatable, Sendable {
    public let blocks: [MarkdownBlock]
    public let plainFallback: Bool

    init(_ blocks: [MarkdownBlock], plainFallback: Bool = false) {
        self.blocks = blocks; self.plainFallback = plainFallback
    }
}

enum MarkdownLimit: Error { case exceeded }

final class MarkdownBudget {
    private var nodes = 0

    func visit(_ depth: Int) throws {
        nodes += 1
        guard nodes <= 4096, depth <= 32 else { throw MarkdownLimit.exceeded }
    }

    func literal(_ value: String) throws {
        guard value.utf8.count <= 16 * 1024 else { throw MarkdownLimit.exceeded }
    }

    /// Bound recursive library conversion before walking its AST; excess input remains fully readable.
    static func accepts(_ source: String) -> Bool {
        guard source.utf8.count <= 128 * 1024 else { return false }
        var markers = 0, lines = 1, pipes = 0
        for byte in source.utf8 {
            switch byte {
            case 42, 45, 62, 91, 93, 95, 126: markers += 1
            case 10: lines += 1; pipes = 0
            case 124: pipes += 1
            default: break
            }
            if markers > 256 || lines > 1024 || pipes > 64 {
                return false
            }
        }
        return true
    }
}

func plainMarkdown(_ source: String) -> MarkdownDocument {
    var blocks: [MarkdownBlock] = []
    var chunk = String.UnicodeScalarView()
    var count = 0
    for scalar in source.unicodeScalars {
        chunk.append(scalar)
        count += 1
        if count == 2048 {
            blocks.append(MarkdownBlock(.text([MarkdownRun(String(chunk))])))
            chunk = String.UnicodeScalarView()
            count = 0
        }
    }
    if !chunk.isEmpty {
        blocks.append(MarkdownBlock(.text([MarkdownRun(String(chunk))])))
    }
    return MarkdownDocument(blocks, plainFallback: true)
}
