import CoreGraphics
import MindCore
import PhotosUI
import SwiftUI

struct ChatAvatarPickerSheet: View {
    @ObservedObject var model: ChatAvatarModel
    @ObservedObject var turn: ChatTurnModel
    let picker: ChatAvatarPicker
    let images: AvatarImageLoader<CGImage>?
    @State private var selection: PhotosPickerItem?
    @State private var preparing = false
    @State private var error: String?

    private var enabled: Bool {
        turn.state.editable && !model.state.busy && !preparing && model.state.pendingSave == nil
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    AvatarImageView(
                        source: AvatarPresentation(images: images, resource: model.state.resource(for: picker.target),
                                                   fallback: .fallback(for: picker.target.mode)),
                        size: 80,
                        description: "当前会话头像"
                    )
                    Text("选择预设，或从照片中生成静态头像。原图最大 20 MB。")
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 80))], spacing: 16) {
                        ForEach(Array(ChatAvatarResource.presets(for: picker.target.mode).enumerated()),
                                id: \.offset)
                        { index, path in
                            if let resource = try? ChatAvatarResource(path) {
                                Button { model.selectPreset(resource, picker: picker) } label: {
                                    VStack {
                                        AvatarImageView(source: AvatarPresentation(images: images, resource: resource,
                                                                                   fallback: .fallback(for: picker
                                                                                       .target.mode)))
                                        Text("预设 \(index + 1)")
                                        if model.state
                                            .resource(for: picker.target) == resource
                                        {
                                            Text("已选").font(.caption)
                                        }
                                    }
                                }.disabled(!enabled)
                            }
                        }
                    }
                    PhotosPicker(selection: $selection, matching: .images, preferredItemEncoding: .current) {
                        Text("从照片选择")
                    }.disabled(!enabled).accessibilityIdentifier("chat_avatar_photo")
                    Button("恢复默认头像") { model.selectPreset(nil, picker: picker) }.disabled(!enabled)
                    if preparing {
                        ProgressView("正在处理图片…")
                    }
                    if let error {
                        Text(error)
                    }
                    if let notice = model.state.notice {
                        Text(notice)
                    }
                    AvatarRecovery(model: model, enabled: turn.state.editable && !preparing)
                }.padding(20)
            }
            .navigationTitle("会话头像").navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("关闭", action: model.dismiss).disabled(model.state.busy || preparing)
                }
            }
        }
        .interactiveDismissDisabled(model.state.busy || preparing)
        .task(id: selection) {
            guard let selection else { return }
            preparing = true; error = nil
            defer { preparing = false; self.selection = nil }
            do {
                guard let photo = try await selection.loadTransferable(type: AvatarPhotoTransfer.self)
                else { throw AvatarImageFailure.invalidImage }
                try Task.checkCancellation()
                model.upload(photo.prepared.data, format: photo.prepared.format, picker: picker)
            } catch {
                guard !Task.isCancelled else { return }
                self.error = "无法读取这张图片。请选择 20 MB 以内、尺寸不过大的系统支持图片。"
            }
        }
    }
}
