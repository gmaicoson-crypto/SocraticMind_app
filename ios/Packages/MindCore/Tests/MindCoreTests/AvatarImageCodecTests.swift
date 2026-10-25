import CoreGraphics
import Foundation
import ImageIO
@testable import MindCore
import Testing
import UniformTypeIdentifiers

struct AvatarImageCodecTests {
    @Test
    func thumbnailsAndUploadsHaveSeparateBoundedDimensionsAndBitmapCosts() throws {
        let data = try encodedImage(width: 1024, height: 512)
        let thumbnail = try AvatarImageCodec.thumbnail(data)
        #expect(thumbnail.image.width == 256); #expect(thumbnail.image.height == 128)
        #expect(thumbnail.bytes == thumbnail.image.bytesPerRow * 128)
        let upload = try AvatarImageCodec.prepare(data: data)
        #expect(upload.format == .png)
        let image = try sourceImage(upload.data)
        #expect(image.width == 512); #expect(image.height == 256)
        #expect(upload.data.count <= ChatAvatarResource.maximumImageBytes)
        let small = try AvatarImageCodec.prepare(data: encodedImage(width: 8, height: 16))
        #expect(try sourceImage(small.data).width == 8)
        #expect(try sourceImage(small.data).height == 16)
    }

    @Test
    func jpegOrientationIsAppliedAndOriginalLocationAndExifMetadataAreRemoved() throws {
        let metadata: [CFString: Any] = [
            kCGImagePropertyOrientation: 6,
            kCGImagePropertyGPSDictionary: [kCGImagePropertyGPSLatitude: 12.5, kCGImagePropertyGPSLatitudeRef: "N"],
            kCGImagePropertyExifDictionary: [kCGImagePropertyExifDateTimeOriginal: "2020:01:02 03:04:05"],
        ]
        let original = try encodedImage(width: 8, height: 16, type: .jpeg, properties: metadata)
        let sourceProperties = try imageProperties(original)
        #expect(sourceProperties[kCGImagePropertyOrientation] as? Int == 6)
        let sourceGPS = try #require(sourceProperties[kCGImagePropertyGPSDictionary] as? [CFString: Any])
        let sourceExif = try #require(sourceProperties[kCGImagePropertyExifDictionary] as? [CFString: Any])
        #expect(sourceGPS[kCGImagePropertyGPSLatitude] as? Double == 12.5)
        #expect(sourceExif[kCGImagePropertyExifDateTimeOriginal] as? String == "2020:01:02 03:04:05")
        let prepared = try AvatarImageCodec.prepare(data: original)
        let image = try sourceImage(prepared.data), properties = try imageProperties(prepared.data)
        #expect(image.width == 16); #expect(image.height == 8)
        #expect(properties[kCGImagePropertyGPSDictionary] == nil)
        let exif = properties[kCGImagePropertyExifDictionary] as? [CFString: Any]
        // ImageIO may add color-space/dimension fields; none of the source's private metadata may survive.
        #expect(exif?[kCGImagePropertyExifDateTimeOriginal] == nil)
        #expect(properties[kCGImagePropertyOrientation] == nil || properties[kCGImagePropertyOrientation] as? Int == 1)
        // Original top half is red; rotation must preserve both colors rather than replacing image contents.
        let colors = try imagePixels(image)
        #expect(colors.contains { $0.0 > 180 && $0.1 < 80 })
        #expect(colors.contains { $0.1 > 180 && $0.0 < 80 })
    }

    @Test
    func animatedGifUsesOnlyTheFirstFrameAndWebpPresetDecodes() throws {
        let first = try bitmap(width: 16, height: 8), second = try bitmap(width: 8, height: 16)
        let data = NSMutableData()
        let destination = try #require(CGImageDestinationCreateWithData(
            data,
            UTType.gif.identifier as CFString,
            2,
            nil
        ))
        CGImageDestinationAddImage(destination, first, nil); CGImageDestinationAddImage(destination, second, nil)
        #expect(CGImageDestinationFinalize(destination))
        let prepared = try AvatarImageCodec.prepare(data: data as Data)
        let source = try #require(CGImageSourceCreateWithData(prepared.data as CFData, nil))
        #expect(CGImageSourceGetCount(source) == 1)
        #expect(try sourceImage(prepared.data).width == 16)
        var root = URL(fileURLWithPath: #filePath)
        for _ in 0 ..< 6 {
            root.deleteLastPathComponent()
        }
        let preset = try Data(contentsOf: root
            .appendingPathComponent("backend/assets/avatars/AI/normal/AI_normal.webp"))
        let thumbnail = try AvatarImageCodec.thumbnail(preset)
        #expect(max(thumbnail.image.width, thumbnail.image.height) <= 256)
        #expect(try sourceImage(AvatarImageCodec.prepare(data: preset).data).width > 0)
    }

    @Test
    func heicInputBecomesAStaticPng() throws {
        let data = try encodedImage(width: 64, height: 32, type: .heic)
        let result = try AvatarImageCodec.prepare(data: data)
        let source = try #require(CGImageSourceCreateWithData(result.data as CFData, nil))
        #expect(CGImageSourceGetType(source) as String? == UTType.png.identifier)
        #expect(CGImageSourceGetCount(source) == 1)
        #expect(try sourceImage(result.data).width == 64)
    }

    @Test
    func malformedDisallowedAndOversizedInputsFailBeforeAnUpload() throws {
        for data in [Data(), Data([0, 1, 2]), Data(repeating: 0, count: AvatarImagePolicy.maximumSourceBytes + 1)] {
            #expect(throws: AvatarImageFailure.self) { try AvatarImageCodec.prepare(data: data) }
        }
        let tiff = try encodedImage(width: 8, height: 8, type: .tiff)
        #expect(throws: AvatarImageFailure.self) { try AvatarImageCodec.prepare(data: tiff) }
        #expect(throws: AvatarImageFailure.self) {
            try AvatarImageCodec.thumbnail(Data(repeating: 0, count: ChatAvatarResource.maximumImageBytes + 1))
        }
        for (width, height) in [(0, 1), (1, -1), (16385, 1), (8193, 8193), (Int.max, Int.max)] {
            #expect(throws: AvatarImageFailure.self) { try AvatarImagePolicy.validate(
                width: width,
                height: height,
                edge: 512
            ) }
        }
        try AvatarImagePolicy.validate(width: 8192, height: 8192, edge: 512)
        #expect(throws: AvatarImageFailure.self) { try AvatarImagePolicy.validate(width: 1, height: 1, edge: 513) }
    }

    @Test
    func fileImportChecksActualBytesAndRejectsNonFiles() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let file = directory.appendingPathComponent("synthetic-image")
        let image = try encodedImage(width: 8, height: 8)
        try image.write(to: file)
        #expect(try AvatarImagePolicy.read(file) == image)
        #expect(try sourceImage(AvatarImageCodec.prepare(file).data).width == 8)
        let handle = try FileHandle(forWritingTo: file)
        try handle.truncate(atOffset: UInt64(AvatarImagePolicy.maximumSourceBytes))
        #expect(try AvatarImagePolicy.read(file).count == AvatarImagePolicy.maximumSourceBytes)
        try handle.truncate(atOffset: UInt64(AvatarImagePolicy.maximumSourceBytes + 1)); try handle.close()
        #expect(throws: AvatarImageFailure.self) { try AvatarImagePolicy.read(file) }
        try Data().write(to: file)
        #expect(throws: AvatarImageFailure.self) { try AvatarImagePolicy.read(file) }
        #expect(throws: AvatarImageFailure.self) {
            try AvatarImagePolicy.read(#require(URL(string: "https://example.invalid/image")))
        }
    }

    @Test
    func cancelledDecodeAndFileReadReturnBeforeDoingWork() async throws {
        let data = try encodedImage(width: 8, height: 8)
        let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try data.write(to: file)
        defer { try? FileManager.default.removeItem(at: file) }
        let cancelled = Task {
            withUnsafeCurrentTask { $0?.cancel() }
            #expect(throws: CancellationError.self) { try AvatarImageCodec.prepare(data: data) }
            #expect(throws: CancellationError.self) { try AvatarImageCodec.thumbnail(data) }
            #expect(throws: CancellationError.self) { try AvatarImagePolicy.read(file) }
            return true
        }
        #expect(await cancelled.value)
    }
}

private func encodedImage(width: Int, height: Int, type: UTType = .png,
                          properties: [CFString: Any] = [:]) throws -> Data
{
    let data = NSMutableData()
    let destination = try #require(CGImageDestinationCreateWithData(data, type.identifier as CFString, 1, nil))
    try CGImageDestinationAddImage(destination, bitmap(width: width, height: height), properties as CFDictionary)
    #expect(CGImageDestinationFinalize(destination))
    return data as Data
}

private func bitmap(width: Int, height: Int) throws -> CGImage {
    let context = try #require(CGContext(
        data: nil,
        width: width,
        height: height,
        bitsPerComponent: 8,
        bytesPerRow: width * 4,
        space: CGColorSpaceCreateDeviceRGB(),
        bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
    ))
    context.setFillColor(CGColor(red: 1, green: 0, blue: 0, alpha: 1))
    context.fill(CGRect(x: 0, y: 0, width: width, height: height / 2))
    context.setFillColor(CGColor(red: 0, green: 1, blue: 0, alpha: 1))
    context.fill(CGRect(x: 0, y: height / 2, width: width, height: height - height / 2))
    return try #require(context.makeImage())
}

private func sourceImage(_ data: Data) throws -> CGImage {
    let source = try #require(CGImageSourceCreateWithData(data as CFData, nil))
    return try #require(CGImageSourceCreateImageAtIndex(source, 0, nil))
}

private func imageProperties(_ data: Data) throws -> [CFString: Any] {
    let source = try #require(CGImageSourceCreateWithData(data as CFData, nil))
    return try #require(CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any])
}

private func imagePixels(_ image: CGImage) throws -> [(UInt8, UInt8)] {
    let bytes = try #require(image.dataProvider?.data) as Data
    return stride(from: 0, to: bytes.count, by: 4).map { (bytes[$0], bytes[$0 + 1]) }
}
