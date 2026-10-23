import MindCore
import SwiftUI

@MainActor
final class AppModel: ObservableObject {
    @Published private(set) var session: SessionState = .uninitialized
    @Published private(set) var error: String?
    let form: AuthFormModel?
    let history: ChatLibraryModel?
    let configurationError: String?
    private let store: SessionStore?
    private var observation: Task<Void, Never>?
    private var formTask: Task<Void, Never>?
    private var sessionTask: Task<Void, Never>?
    private var formRunning = false
    private var sessionRunning = false

    init() {
        do {
            let address = Bundle.main.object(forInfoDictionaryKey: "SocraticMindAPIBaseURL") as? String ?? ""
            #if DEBUG
                let allowed: Set = ["127.0.0.1", "localhost"]
            #else
                let allowed: Set<String> = []
            #endif
            let endpoint = try APIEndpoint(address, developmentHTTPHosts: allowed)
            let transport = try HTTPTransport(endpoint: endpoint)
            let api = AuthAPI(transport: transport)
            let session = SessionStore(gateway: api, vault: KeychainTokenVault(endpoint: endpoint))
            store = session
            form = AuthFormModel(session: session, recovery: api)
            history = ChatLibraryModel(session: session, gateway: ChatHistoryAPI(transport: transport))
            configurationError = nil
        } catch {
            store = nil
            form = nil
            history = nil
            configurationError = "服务地址未正确配置，请检查当前开发配置。"
        }
    }

    func start() {
        guard observation == nil, let store else { return }
        observation = Task { [weak self] in
            var revision: UInt64?
            for await state in await store.updates() {
                guard !Task.isCancelled, let self else { return }
                let next: UInt64? = if case let .signedIn(_, value) = state {
                    value
                } else {
                    nil
                }
                if next != revision {
                    form?.reset(); revision = next
                }
                history?.bindAccount(state)
                session = state
            }
        }
        restore()
    }

    func submit() {
        runForm { await $0.submit() }
    }

    func sendCode() {
        runForm { await $0.sendCode() }
    }

    func restore() {
        runSession { try await $0.restore() }
    }

    func logout() {
        guard !sessionRunning else { return }
        formTask?.cancel()
        form?.reset()
        history?.clear()
        runSession { try await $0.logout() }
    }

    private func runForm(_ action: @escaping @MainActor (AuthFormModel) async -> Void) {
        guard !formRunning, !sessionRunning, let form else { return }
        formRunning = true
        error = nil
        formTask = Task { [weak self] in
            await action(form)
            self?.formRunning = false
            self?.formTask = nil
        }
    }

    private func runSession(_ action: @escaping @Sendable (SessionStore) async throws -> Void) {
        guard !sessionRunning, let store else { return }
        sessionRunning = true
        error = nil
        sessionTask = Task { [weak self] in
            defer { self?.sessionRunning = false; self?.sessionTask = nil }
            do { try await action(store) }
            catch {
                guard !(error is CancellationError) else { return }
                if case .signedOut = await store.state {
                    return
                }
                self?.error = accountErrorMessage(error)
            }
        }
    }

    deinit {
        observation?.cancel()
        formTask?.cancel()
        sessionTask?.cancel()
    }
}
