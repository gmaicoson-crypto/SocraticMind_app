import CoreGraphics
import MindCore
import SwiftUI

struct AvatarPresentation {
    let images: AvatarImageLoader<CGImage>?
    let resource: ChatAvatarResource
    let fallback: ChatAvatarResource
}

struct AvatarImageView: View {
    let source: AvatarPresentation
    var size: CGFloat = 40
    var description: String?
    @State private var frame: Frame?
    private struct Key: Equatable { let scope: UUID?; let resource: String; let fallback: String }
    private struct Frame { let key: Key; let image: CGImage }
    private var key: Key {
        Key(scope: source.images?.id, resource: source.resource.path, fallback: source.fallback.path)
    }

    var body: some View {
        ZStack {
            Circle().fill(.secondary.opacity(0.15))
            if let frame, frame.key == key {
                Image(decorative: frame.image, scale: 1, orientation: .up)
                    .resizable().scaledToFill()
            } else {
                Text("AI").font(.caption).foregroundStyle(.secondary)
            }
        }
        .frame(width: size, height: size).clipShape(Circle())
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(description ?? "")
        .accessibilityHidden(description == nil)
        .task(id: key) {
            frame = nil
            guard let images = source.images else { return }
            let requested = key
            var image: CGImage?
            do { image = try await images.load(source.resource) }
            catch {
                guard !Task.isCancelled, source.resource != source.fallback else { return }
                image = try? await images.load(source.fallback)
            }
            if let image, !Task.isCancelled {
                frame = Frame(key: requested, image: image)
            }
        }
    }
}
