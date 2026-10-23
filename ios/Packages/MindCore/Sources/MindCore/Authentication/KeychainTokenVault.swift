import CryptoKit
import Foundation
import Security

public enum KeychainFailure: Error, Sendable {
    case invalidData
    case status(OSStatus)
}

/// Synchronous calls run on SessionStore's actor, never in a View's body.
public struct KeychainTokenVault: TokenVault {
    private let identity: String
    private let client: any KeychainClient
    private let service = "com.gmaicoson.socraticmind.session"

    public init(endpoint: APIEndpoint) {
        self.init(endpoint: endpoint, client: SystemKeychainClient())
    }

    init(endpoint: APIEndpoint, client: any KeychainClient) {
        identity = SHA256.hash(data: Data(endpoint.credentialScope.utf8))
            .map { String(format: "%02x", $0) }.joined()
        self.client = client
    }

    private var query: [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: identity,
            kSecAttrSynchronizable as String: false,
            kSecUseDataProtectionKeychain as String: true,
        ]
    }

    public func read() throws -> String? {
        var request = query
        request[kSecReturnData as String] = true
        request[kSecMatchLimit as String] = kSecMatchLimitOne
        let (status, data) = client.copy(request)
        if status == errSecItemNotFound {
            return nil
        }
        guard status == errSecSuccess else { throw KeychainFailure.status(status) }
        guard let data, data.count <= 16 * 1024, let token = String(data: data, encoding: .utf8) else {
            throw KeychainFailure.invalidData
        }
        try validate(token)
        return token
    }

    public func write(_ token: String) throws {
        try validate(token)
        let values: [String: Any] = [
            kSecValueData as String: Data(token.utf8),
            kSecAttrAccessible as String: kSecAttrAccessibleWhenUnlockedThisDeviceOnly,
        ]
        var status = client.update(query, values: values)
        if status == errSecItemNotFound {
            status = client.add(query.merging(values) { _, new in new })
            if status == errSecDuplicateItem {
                status = client.update(query, values: values)
            }
        }
        guard status == errSecSuccess else { throw KeychainFailure.status(status) }
    }

    public func clear() throws {
        let status = client.delete(query)
        guard status == errSecSuccess || status == errSecItemNotFound else {
            throw KeychainFailure.status(status)
        }
    }

    private func validate(_ token: String) throws {
        guard !token.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              !token.contains("\r"), !token.contains("\n"), token.utf8.count <= 16 * 1024
        else { throw KeychainFailure.invalidData }
    }
}

protocol KeychainClient: Sendable {
    func copy(_ query: [String: Any]) -> (OSStatus, Data?)
    func update(_ query: [String: Any], values: [String: Any]) -> OSStatus
    func add(_ attributes: [String: Any]) -> OSStatus
    func delete(_ query: [String: Any]) -> OSStatus
}

private struct SystemKeychainClient: KeychainClient {
    func copy(_ query: [String: Any]) -> (OSStatus, Data?) {
        var result: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        return (status, result as? Data)
    }

    func update(_ query: [String: Any], values: [String: Any]) -> OSStatus {
        SecItemUpdate(query as CFDictionary, values as CFDictionary)
    }

    func add(_ attributes: [String: Any]) -> OSStatus {
        SecItemAdd(attributes as CFDictionary, nil)
    }

    func delete(_ query: [String: Any]) -> OSStatus {
        SecItemDelete(query as CFDictionary)
    }
}
