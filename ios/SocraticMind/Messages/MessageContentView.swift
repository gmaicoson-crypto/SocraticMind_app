import MindCore
import SwiftUI

struct MessageContentView: View {
    let role: String
    let content: String
    let attachmentCount: Int
    let renderer: MarkdownRenderer
    let provisional: Bool
    let avatar: AvatarPresentation?

    init(message: StoredChatMessage, renderer: MarkdownRenderer, avatar: AvatarPresentation? = nil) {
        role = message.role; content = message.content; attachmentCount = message.attachments.count
        self.renderer = renderer; provisional = false
        self.avatar = avatar
    }

    init(role: String, content: String, renderer: MarkdownRenderer, provisional: Bool = false,
         avatar: AvatarPresentation? = nil)
    {
        self.role = role; self.content = content; attachmentCount = 0
        self.renderer = renderer; self.provisional = provisional
        self.avatar = avatar
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                if role != "user", let avatar {
                    AvatarImageView(source: avatar, size: 32)
                }
                Text(role == "user" ? "你" : "SocraticMind").font(.caption).foregroundStyle(.tint)
                Spacer()
                MessageCopyButton(text: content, label: provisional ? "复制当前文字" : "复制原文")
            }
            if provisional {
                Text(content.isEmpty ? "正在等待回复…" : content).lineLimit(32).textSelection(.enabled)
            } else {
                MarkdownBodyView(source: content, renderer: renderer)
            }
            if attachmentCount > 0 {
                Text("包含 \(attachmentCount) 个附件").font(.caption).foregroundStyle(.secondary)
            }
        }
        .padding(.vertical, 8)
    }
}

private struct RenderedMarkdown {
    let source: String
    let document: MarkdownDocument?
}

private struct MarkdownBodyView: View {
    let source: String
    let renderer: MarkdownRenderer
    @State private var rendered: RenderedMarkdown?

    var body: some View {
        Group {
            if let rendered, rendered.source == source {
                if let document = rendered.document {
                    MarkdownDocumentView(document: document).id(source)
                } else {
                    Text("暂时无法显示消息，仍可复制原文。").foregroundStyle(.secondary)
                }
            } else {
                ProgressView("正在排版…")
            }
        }
        .task(id: source) {
            do {
                let document = try await renderer.render(source)
                try Task.checkCancellation()
                rendered = RenderedMarkdown(source: source, document: document)
            } catch is CancellationError {
                // A disappearing/reused row cannot update a new message or account.
            } catch {
                rendered = RenderedMarkdown(source: source, document: nil)
            }
        }
    }
}

private struct MarkdownDocumentView: View {
    let document: MarkdownDocument
    @State private var visibleBlocks = 24
    @State private var linkError = false
    @Environment(\.openURL) private var openURL

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if document.plainFallback {
                Text("此消息按原文分段显示。").font(.caption).foregroundStyle(.secondary)
            }
            ForEach(Array(document.blocks.prefix(visibleBlocks).enumerated()), id: \.offset) { _, block in
                MarkdownBlockView(block: block)
            }
            if visibleBlocks < document.blocks.count {
                Button("显示更多内容（剩余 \(document.blocks.count - visibleBlocks) 段）") { visibleBlocks += 24 }
                    .buttonStyle(.borderless)
            }
            if linkError {
                Text("无法打开这个链接。").font(.caption).foregroundStyle(.secondary)
            }
        }
        .environment(\.openURL, OpenURLAction { url in
            guard let safe = MarkdownLink.safe(url.absoluteString), let target = URL(string: safe) else {
                linkError = true
                return .discarded
            }
            openURL(target) { accepted in linkError = !accepted }
            return .handled
        })
    }
}
