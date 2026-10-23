import Markdown

struct MarkdownInlineProjection {
    let budget: MarkdownBudget

    func runs(_ parent: any Markup) throws -> [MarkdownRun] {
        var result: [MarkdownRun] = []
        for child in parent.children {
            try visit(child, style: MarkdownStyle(), link: nil, result: &result, depth: 0)
        }
        return result
    }

    private func visit(_ node: any Markup, style: MarkdownStyle, link: String?, result: inout [MarkdownRun],
                       depth: Int) throws
    {
        try budget.visit(depth)
        switch node {
        case let text as Markdown.Text: try append(text.string, style: style, link: link, to: &result)
        case let html as InlineHTML: try append(html.rawHTML, style: style, link: nil, to: &result)
        case let code as InlineCode:
            var codeStyle = style; codeStyle.code = true
            try append(code.code, style: codeStyle, link: link, to: &result)
        case is SoftBreak, is LineBreak: try append("\n", style: style, link: link, to: &result)
        case is Image:
            try append("[图片：", style: style, link: nil, to: &result)
            var alt: [MarkdownRun] = []
            for child in node.children {
                try visit(child, style: style, link: nil, result: &alt, depth: depth + 1)
            }
            for run in alt {
                try append(run.text, style: run.style, link: nil, to: &result)
            }
            try append("]", style: style, link: nil, to: &result)
        default:
            var next = style
            if node is Strong {
                next.bold = true
            }
            if node is Emphasis {
                next.italic = true
            }
            if node is Strikethrough {
                next.strike = true
            }
            let target = if let node = node as? Link {
                MarkdownLink.safe(node.destination ?? "")
            } else {
                link
            }
            for child in node
                .children
            {
                try visit(child, style: next, link: target, result: &result, depth: depth + 1)
            }
        }
    }

    private func append(_ text: String, style: MarkdownStyle, link: String?, to result: inout [MarkdownRun]) throws {
        guard !text.isEmpty else { return }
        try budget.literal(text)
        if let last = result.last, last.style == style, last.link == link {
            let merged = last.text + text
            try budget.literal(merged)
            result[result.count - 1] = MarkdownRun(merged, style: style, link: link)
        } else {
            result.append(MarkdownRun(text, style: style, link: link))
        }
    }
}
