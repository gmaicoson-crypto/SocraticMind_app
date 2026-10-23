import SwiftUI
import UIKit

struct MessageCopyButton: View {
    let text: String
    let label: String
    @State private var copied = false

    var body: some View {
        Button(copied ? "已复制" : label) {
            UIPasteboard.general.setItems([["public.utf8-plain-text": text]], options: [.localOnly: true])
            copied = true
        }
        .font(.caption).buttonStyle(.borderless)
        .onChange(of: text) { _, _ in copied = false }
    }
}
