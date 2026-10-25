import Foundation

public enum AvatarImageFailure: Error { case invalidImage, sourceTooLarge, dimensions, queueFull, decodedTooLarge }

public enum AvatarImagePolicy {
    public static let maximumSourceBytes = 20 * 1024 * 1024
    public static let displayEdge = 256
    public static let uploadEdge = 512
    public static let maximumEdge = 16384
    public static let maximumPixels = 64 * 1024 * 1024

    public static func validate(width: Int, height: Int, edge: Int) throws {
        guard (1 ... maximumEdge).contains(width), (1 ... maximumEdge).contains(height),
              width * height <= maximumPixels, (1 ... uploadEdge).contains(edge)
        else { throw AvatarImageFailure.dimensions }
    }

    public static func read(_ url: URL) throws -> Data {
        try Task.checkCancellation()
        guard url.isFileURL else { throw AvatarImageFailure.invalidImage }
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        var data = Data()
        while true {
            try Task.checkCancellation()
            let chunk = try handle.read(upToCount: min(64 * 1024, maximumSourceBytes - data.count + 1)) ?? Data()
            if chunk.isEmpty {
                break
            }
            guard data.count + chunk.count <= maximumSourceBytes else { throw AvatarImageFailure.sourceTooLarge }
            data.append(chunk)
        }
        guard !data.isEmpty else { throw AvatarImageFailure.invalidImage }
        return data
    }
}
