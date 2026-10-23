import MindCore
import SwiftUI

struct MarkdownBlockView: View {
    let block: MarkdownBlock

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            if block.quoteDepth > 0 {
                Text(verbatim: String(repeating: "│", count: min(block.quoteDepth, 3))).foregroundStyle(.secondary)
            }
            if let marker = block.marker {
                Text(verbatim: marker)
            }
            content.frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(.leading, CGFloat(min(block.indent, 6) * 12))
    }

    @ViewBuilder
    private var content: some View {
        switch block.content {
        case let .text(runs, heading): MarkdownInlineView(runs: runs, heading: heading)
        case let .code(text, language): MarkdownCodeView(text: text, language: language)
        case let .table(table): MarkdownTableView(table: table)
        case .rule: Divider().padding(.vertical, 8)
        }
    }
}

private struct MarkdownCodeView: View {
    let text: String
    let language: String
    @ScaledMetric(relativeTo: .body) private var lineHeight: CGFloat = 22

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(verbatim: language.isEmpty ? "代码" : language).font(.caption)
                Spacer()
                MessageCopyButton(text: text, label: "复制代码")
            }
            ScrollView([.horizontal, .vertical]) {
                Text(verbatim: text).font(.system(.body, design: .monospaced))
                    .fixedSize(horizontal: true, vertical: true).textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .frame(height: CGFloat(min(10, text.lazy.filter { $0 == "\n" }.prefix(10).count + 1)) * lineHeight + 16)
        }
        .padding(12).background(.quaternary, in: RoundedRectangle(cornerRadius: 8))
    }
}

private struct MarkdownTableView: View {
    let table: MarkdownTable
    @State private var visibleRows = 21

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            ScrollView(.horizontal) {
                VStack(alignment: .leading, spacing: 0) {
                    ForEach(Array(table.rows.prefix(visibleRows).enumerated()), id: \.offset) { rowIndex, row in
                        HStack(alignment: .top, spacing: 0) {
                            ForEach(Array(row.enumerated()), id: \.offset) { column, runs in
                                MarkdownInlineView(runs: runs, bold: rowIndex == 0, alignment: textAlignment(column))
                                    .padding(8).frame(width: 180, alignment: cellAlignment(column))
                            }
                        }
                        .background(rowIndex == 0 ? Color.secondary.opacity(0.12) : Color.clear)
                        Divider()
                    }
                }
            }
            if visibleRows < table.rows.count {
                Button("显示更多表格行（剩余 \(table.rows.count - visibleRows)）") { visibleRows += 20 }
                    .font(.caption).buttonStyle(.borderless)
            }
        }
    }

    private func textAlignment(_ column: Int) -> TextAlignment {
        switch table.alignments[column] {
        case .left: .leading
        case .center: .center
        case .right: .trailing
        }
    }

    private func cellAlignment(_ column: Int) -> Alignment {
        switch table.alignments[column] {
        case .left: .leading
        case .center: .center
        case .right: .trailing
        }
    }
}
