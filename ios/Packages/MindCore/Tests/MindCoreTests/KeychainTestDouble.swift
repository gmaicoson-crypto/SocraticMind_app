import Foundation
@testable import MindCore
import Security

/// All mutable state, including synthetic failures, is protected by the same lock.
final class FakeKeychainClient: KeychainClient, @unchecked Sendable {
    private let lock = NSLock()
    private var items: [String: [String: Any]] = [:]
    private var failures: [String: OSStatus] = [:]
    private var malformedData: Data?
    private var lastRequest: [String: Any] = [:]

    func fail(_ operation: String, status: OSStatus?) {
        lock.withLock { failures[operation] = status }
    }

    func corrupt(_ data: Data) {
        lock.withLock { malformedData = data }
    }

    func attributes() -> [String: Any] {
        lock.withLock { items.values.first ?? [:] }
    }

    func request() -> [String: Any] {
        lock.withLock { lastRequest }
    }

    func count() -> Int {
        lock.withLock { items.count }
    }

    private func key(_ query: [String: Any]) -> String {
        "\(query[kSecAttrService as String] ?? "missing")|\(query[kSecAttrAccount as String] ?? "missing")"
    }

    func copy(_ query: [String: Any]) -> (OSStatus, Data?) {
        lock.withLock {
            lastRequest = query
            if let failure = failures["read"] {
                return (failure, nil)
            }
            guard let item = items[key(query)] else { return (errSecItemNotFound, nil) }
            return (errSecSuccess, malformedData ?? item[kSecValueData as String] as? Data)
        }
    }

    func update(_ query: [String: Any], values: [String: Any]) -> OSStatus {
        lock.withLock {
            lastRequest = query
            if let failure = failures["write"] {
                return failure
            }
            guard let existing = items[key(query)] else { return errSecItemNotFound }
            items[key(query)] = existing.merging(values) { _, new in new }
            return errSecSuccess
        }
    }

    func add(_ attributes: [String: Any]) -> OSStatus {
        lock.withLock {
            lastRequest = attributes
            if let failure = failures["write"] {
                return failure
            }
            guard items[key(attributes)] == nil else { return errSecDuplicateItem }
            items[key(attributes)] = attributes
            return errSecSuccess
        }
    }

    func delete(_ query: [String: Any]) -> OSStatus {
        lock.withLock {
            lastRequest = query
            if let failure = failures["delete"] {
                return failure
            }
            return items.removeValue(forKey: key(query)) == nil ? errSecItemNotFound : errSecSuccess
        }
    }
}
