import Foundation

struct AvatarFixture: Decodable {
    let owner_id: Int64
    let session_id: String
    let upload_url: String
    let image_base64: String
    let presets: [String: [String]]
    let invalid_paths: [String]
    var image: Data {
        Data(base64Encoded: image_base64)!
    }
}

func avatarFixture() throws -> AvatarFixture {
    var root = URL(fileURLWithPath: #filePath)
    for _ in 0 ..< 6 {
        root.deleteLastPathComponent()
    }
    return try JSONDecoder().decode(AvatarFixture.self, from: Data(contentsOf: root
            .appendingPathComponent("contracts/fixtures/chat-avatar.json")))
}
