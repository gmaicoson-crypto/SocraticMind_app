import CoreGraphics
import MindCore
import SwiftUI

struct ChatAvatarControls: View {
    @ObservedObject var model: ChatAvatarModel
    let images: AvatarImageLoader<CGImage>?
    let target: ChatTarget?
    let enabled: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let target {
                HStack {
                    AvatarImageView(source: AvatarPresentation(
                        images: images,
                        resource: model.state.resource(for: target),
                        fallback: .fallback(for: target.mode)
                    ))
                    Button("更换会话头像") { model.open(target) }
                        .disabled(!enabled || !model.state.loaded || model.state.loading || model.state.busy ||
                            model.state.pendingSave != nil)
                        .accessibilityIdentifier("chat_avatar_open")
                }
            }
            if model.state.picker == nil {
                if let notice = model.state.notice {
                    Text(notice)
                }
                AvatarRecovery(model: model, enabled: enabled)
            }
        }.frame(maxWidth: .infinity, alignment: .leading).padding(.horizontal, 20)
    }
}

struct AvatarRecovery: View {
    @ObservedObject var model: ChatAvatarModel
    let enabled: Bool

    var body: some View {
        if model.state.loading || model.state.busy {
            ProgressView("正在处理头像…")
        } else if model.state.pendingSave != nil {
            VStack(alignment: .leading, spacing: 12) {
                Button("重试保存", action: model.retrySave).accessibilityIdentifier("chat_avatar_retry_save")
                Button("放弃未保存选择", action: model.discardPendingSave)
            }.disabled(!enabled)
        } else if !model.state.loaded {
            Button("重新读取头像记录", action: model.reload)
        }
    }
}
