import MindCore
import SwiftUI

struct MarkdownInlineView: View {
    let runs: [MarkdownRun]
    var heading = 0
    var bold = false
    var alignment: TextAlignment = .leading

    var body: some View {
        Text(attributed).multilineTextAlignment(alignment).textSelection(.enabled)
            .accessibilityAddTraits(heading > 0 ? .isHeader : [])
    }

    private var baseFont: Font {
        switch heading {
        case 1: .title
        case 2: .title2
        case 3: .title3
        case 4 ... 6: .headline
        default: .body
        }
    }

    private var attributed: AttributedString {
        var result = AttributedString()
        for run in runs {
            var piece = AttributedString(run.text)
            var font = baseFont
            if run.style.code {
                font = font.monospaced(); piece.backgroundColor = .secondary.opacity(0.12)
            }
            if run.style.bold || bold {
                font = font.bold()
            }
            if run.style.italic {
                font = font.italic()
            }
            piece.font = font
            if run.style.strike {
                piece.strikethroughStyle = .single
            }
            if let link = run.link, let safe = MarkdownLink.safe(link) {
                piece.link = URL(string: safe)
                piece.underlineStyle = .single
            }
            result.append(piece)
        }
        return result
    }
}
