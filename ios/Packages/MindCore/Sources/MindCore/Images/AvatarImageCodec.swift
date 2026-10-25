import CoreGraphics
import Foundation
import ImageIO
import UniformTypeIdentifiers

public struct PreparedAvatar: Sendable {
    public let data: Data
    public let format: AvatarImageFormat = .png
}

/// Call on an image worker. Only a bounded, oriented first frame reaches the UI or upload API.
public enum AvatarImageCodec {
    public static func thumbnail(_ data: Data) throws -> DecodedAvatar<CGImage> {
        guard data.count <= ChatAvatarResource.maximumImageBytes else { throw AvatarImageFailure.sourceTooLarge }
        let image = try decode(data, edge: AvatarImagePolicy.displayEdge)
        return DecodedAvatar(image: image, bytes: image.bytesPerRow * image.height)
    }

    public static func prepare(_ file: URL) throws -> PreparedAvatar {
        try prepare(data: AvatarImagePolicy.read(file))
    }

    public static func prepare(data: Data) throws -> PreparedAvatar {
        guard data.count <= AvatarImagePolicy.maximumSourceBytes else { throw AvatarImageFailure.sourceTooLarge }
        let image = try decode(data, edge: AvatarImagePolicy.uploadEdge)
        let result = NSMutableData()
        guard let destination = CGImageDestinationCreateWithData(result, UTType.png.identifier as CFString, 1, nil)
        else { throw AvatarImageFailure.invalidImage }
        // No original metadata is copied to the encoded bitmap.
        CGImageDestinationAddImage(destination, image, nil)
        guard CGImageDestinationFinalize(destination), result.length <= ChatAvatarResource.maximumImageBytes
        else { throw AvatarImageFailure.invalidImage }
        try Task.checkCancellation()
        return PreparedAvatar(data: result as Data)
    }

    private static func decode(_ data: Data, edge: Int) throws -> CGImage {
        try Task.checkCancellation()
        let allowed = Set([UTType.png, .jpeg, .gif, .webP, .heic, .heif].map(\.identifier))
        guard !data.isEmpty,
              let source = CGImageSourceCreateWithData(
                  data as CFData,
                  [kCGImageSourceShouldCache: false] as CFDictionary
              ),
              let type = CGImageSourceGetType(source), allowed.contains(type as String),
              let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
              let width = properties[kCGImagePropertyPixelWidth] as? NSNumber,
              let height = properties[kCGImagePropertyPixelHeight] as? NSNumber
        else { throw AvatarImageFailure.invalidImage }
        try AvatarImagePolicy.validate(width: width.intValue, height: height.intValue, edge: edge)
        let options: [CFString: Any] = [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceCreateThumbnailWithTransform: true,
            kCGImageSourceThumbnailMaxPixelSize: edge,
            kCGImageSourceShouldCacheImmediately: true,
        ]
        guard let thumbnail = CGImageSourceCreateThumbnailAtIndex(source, 0, options as CFDictionary),
              (1 ... edge).contains(thumbnail.width), (1 ... edge).contains(thumbnail.height),
              let space = CGColorSpace(name: CGColorSpace.sRGB),
              let context = CGContext(data: nil, width: thumbnail.width, height: thumbnail.height,
                                      bitsPerComponent: 8, bytesPerRow: thumbnail.width * 4, space: space,
                                      bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue |
                                          CGBitmapInfo.byteOrder32Big.rawValue)
        else { throw AvatarImageFailure.invalidImage }
        context.draw(thumbnail, in: CGRect(x: 0, y: 0, width: thumbnail.width, height: thumbnail.height))
        try Task.checkCancellation()
        guard let image = context.makeImage() else { throw AvatarImageFailure.invalidImage }
        return image
    }
}
