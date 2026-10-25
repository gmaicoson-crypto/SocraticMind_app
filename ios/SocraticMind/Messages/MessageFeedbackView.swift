import MindCore
import SwiftUI

/// Shared by ordinary and node messages; usage is optional detail, failure remains visible.
struct MessageFeedbackView: View {
    let feedback: ChatAnswerFeedback
    @State private var expanded = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let failure = feedback.failure {
                Text(failure.message).font(.caption).foregroundStyle(.red)
            }
            DisclosureGroup("模型用量", isExpanded: $expanded) {
                VStack(alignment: .leading, spacing: 8) {
                    Text(feedback.usageSummary)
                    Text(ChatAnswerFeedback.scopeNote).foregroundStyle(.secondary)
                }
                .font(.caption)
            }
            .accessibilityIdentifier("chat_usage")
        }
    }
}
