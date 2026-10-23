import Foundation

public enum AuthDecodingFailure: Error { case invalidUser, invalidToken }

public struct AuthUser: Decodable, Equatable, Sendable {
    public let id: Int64
    public let username: String
    public let email: String
    public let avatarURL: String
    public let aiAvatarURL: String
    public let bio: String
    public let dailyGoal: Int
    public let aiStyle: String

    enum CodingKeys: String, CodingKey {
        case id, username, email, bio
        case avatarURL = "avatar_url", aiAvatarURL = "ai_avatar_url", dailyGoal = "daily_goal", aiStyle = "ai_style"
    }

    public init(from decoder: any Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        id = try values.decode(Int64.self, forKey: .id)
        guard id > 0 else { throw AuthDecodingFailure.invalidUser }
        username = try values.decode(String.self, forKey: .username)
        email = try values.decode(String.self, forKey: .email)
        avatarURL = try values.decode(String.self, forKey: .avatarURL)
        aiAvatarURL = try values.decode(String.self, forKey: .aiAvatarURL)
        bio = try values.decode(String.self, forKey: .bio)
        dailyGoal = try values.decode(Int.self, forKey: .dailyGoal)
        aiStyle = try values.decode(String.self, forKey: .aiStyle)
    }
}

public struct AuthGrant: Decodable, Sendable, CustomStringConvertible {
    public let accessToken: String
    public let user: AuthUser
    public var description: String {
        "AuthGrant(userID=\(user.id), accessToken=<redacted>)"
    }

    enum CodingKeys: String, CodingKey {
        case accessToken = "access_token", tokenType = "token_type", user
    }

    public init(from decoder: any Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        accessToken = try values.decode(String.self, forKey: .accessToken)
        let type = try values.contains(.tokenType) ? values.decode(String.self, forKey: .tokenType) : "bearer"
        guard type.lowercased() == "bearer", !accessToken.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              !accessToken.contains(where: { $0 == "\r" || $0 == "\n" })
        else { throw AuthDecodingFailure.invalidToken }
        user = try values.decode(AuthUser.self, forKey: .user)
    }
}

public enum CodePurpose: String, Sendable { case register, reset }
