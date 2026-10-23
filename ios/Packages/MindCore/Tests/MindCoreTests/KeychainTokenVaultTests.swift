import Foundation
@testable import MindCore
import Security
import Testing

struct KeychainTokenVaultTests {
    @Test
    func credentialIsLocalToDeviceAndCanBeUpdatedAndRemoved() throws {
        let client = FakeKeychainClient()
        let vault = try vault(client)
        #expect(try vault.read() == nil)
        try vault.write("synthetic-one")
        #expect(try vault.read() == "synthetic-one")
        let attributes = client.attributes()
        #expect(attributes[kSecAttrAccessible as String] as? String ==
            kSecAttrAccessibleWhenUnlockedThisDeviceOnly as String)
        #expect(attributes[kSecAttrSynchronizable as String] as? Bool == false)
        #expect(attributes[kSecClass as String] as? String == kSecClassGenericPassword as String)
        #expect(attributes[kSecUseDataProtectionKeychain as String] as? Bool == true)
        try vault.write("synthetic-two")
        #expect(client.count() == 1)
        #expect(try vault.read() == "synthetic-two")
        try vault.clear()
        try vault.clear()
        #expect(try vault.read() == nil)
        #expect(client.request()[kSecMatchLimit as String] as? String == kSecMatchLimitOne as String)
    }

    @Test
    func endpointScopePreventsReadingOrDeletingAnotherBackendCredential() throws {
        let client = FakeKeychainClient()
        let first = try vault(client)
        let equivalent = try vault(client, "HTTPS://API.EXAMPLE.TEST:443/")
        let other = try vault(client, "https://api.example.test/mobile/")
        try first.write("synthetic-first")
        #expect(try equivalent.read() == "synthetic-first")
        #expect(try other.read() == nil)
        try other.write("synthetic-other")
        try first.clear()
        #expect(try other.read() == "synthetic-other")
        #expect(client.count() == 1)
    }

    @Test
    func lockedOrFailedStorageRemainsAnErrorAndPreservesExistingItem() throws {
        let client = FakeKeychainClient()
        let vault = try vault(client)
        try vault.write("synthetic-existing")
        client.fail("read", status: errSecInteractionNotAllowed)
        #expect(throws: KeychainFailure.self) { try vault.read() }
        client.fail("read", status: nil)
        client.fail("write", status: errSecNotAvailable)
        #expect(throws: KeychainFailure.self) { try vault.write("synthetic-replacement") }
        client.fail("write", status: nil)
        client.fail("delete", status: errSecInteractionNotAllowed)
        #expect(throws: KeychainFailure.self) { try vault.clear() }
        #expect(try vault.read() == "synthetic-existing")
    }

    @Test
    func invalidAndOversizedValuesAreRejectedWithoutWritingItems() throws {
        let client = FakeKeychainClient()
        let vault = try vault(client)
        for invalid in ["", "  ", "a\nb", "a\rb", String(repeating: "x", count: 16 * 1024 + 1),
                        String(repeating: "中", count: 6000)]
        {
            #expect(throws: KeychainFailure.self) { try vault.write(invalid) }
        }
        #expect(client.count() == 0)
    }

    @Test
    func malformedStoredBytesDoNotBecomeAUsableTokenOrAnEmptyAccount() throws {
        let client = FakeKeychainClient()
        let vault = try vault(client)
        try vault.write("synthetic-existing")
        for bytes in [Data([0xFF]), Data(), Data("a\nb".utf8), Data(repeating: 65, count: 16 * 1024 + 1)] {
            client.corrupt(bytes)
            #expect(throws: KeychainFailure.self) { try vault.read() }
            #expect(client.count() == 1)
        }
    }

    private func vault(_ client: FakeKeychainClient,
                       _ address: String = "https://api.example.test/") throws -> KeychainTokenVault
    {
        try KeychainTokenVault(endpoint: APIEndpoint(address), client: client)
    }
}
