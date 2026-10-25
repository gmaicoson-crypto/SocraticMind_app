import Combine
import MindCore
import SwiftUI

@MainActor
final class AppModel: ObservableObject {
    @Published private(set) var session: SessionState = .uninitialized
    @Published private(set) var error: String?
    let form: AuthFormModel?
    let history: ChatLibraryModel?
    let turn: ChatTurnModel?
    let actions: ChatActionsModel?
    let suggestions: ChatSuggestionsModel?
    let avatars: ChatAvatarModel?
    let configurationError: String?
    private let store: SessionStore?
    private var observation: Task<Void, Never>?
    private var formTask: Task<Void, Never>?
    private var sessionTask: Task<Void, Never>?
    private var formRunning = false
    private var sessionRunning = false
    private var turnObservation: AnyCancellable?

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
            let directory = try FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask,
                                                        appropriateFor: nil, create: true)
            let journal = try FileChatTurnJournal(directory: directory, endpointScope: endpoint.credentialScope)
            let avatarStore = try FileChatAvatarStore(directory: directory, endpointScope: endpoint.credentialScope)
            store = session
            form = AuthFormModel(session: session, recovery: api)
            let actionsAPI = ChatActionsAPI(transport: transport)
            let library = ChatLibraryModel(session: session, gateway: ChatHistoryAPI(transport: transport),
                                           titles: actionsAPI)
            let coordinator = ChatTurnModel(
                session: session,
                gateway: ChatTurnAPI(transport: transport),
                journal: journal
            )
            history = library; turn = coordinator
            let avatarModel = ChatAvatarModel(session: session, gateway: ChatAvatarAPI(transport: transport),
                                              store: avatarStore, library: library, turn: coordinator)
            avatars = avatarModel
            actions = ChatActionsModel(
                session: session,
                gateway: actionsAPI,
                library: library,
                turn: coordinator,
                onSessionDeleted: { account, id in
                    await avatarModel.forgetDeletedSession(account: account, sessionID: id)
                }
            )
            suggestions = ChatSuggestionsModel(session: session, gateway: ChatSuggestionsAPI(transport: transport),
                                               history: library, turn: coordinator)
            configurationError = nil
        } catch {
            store = nil
            form = nil
            history = nil
            turn = nil
            actions = nil
            suggestions = nil
            avatars = nil
            configurationError = "服务地址未正确配置，请检查当前开发配置。"
        }
        // @Published emits before storing state; acknowledge on the next main-actor turn.
        turnObservation = turn?.$state.sink { [weak self] state in
            Task { @MainActor [weak self] in self?.acceptTurn(state) }
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
                    suggestions?.clear()
                    form?.reset(); revision = next
                }
                history?.bindAccount(state)
                turn?.bindAccount(state)
                avatars?.bindAccount(state)
                actions?.bindAccount(state)
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
        suggestions?.clear()
        avatars?.clear()
        actions?.clear()
        history?.clear()
        turn?.clear()
        runSession { try await $0.logout() }
    }

    func newConversation() {
        guard turn?.state.editable == true, let target = try? ChatTarget(sessionID: UUID().uuidString) else { return }
        actions?.dismiss()
        turn?.select(target); history?.openConversation(target)
    }

    func selectConversation(_ id: String) {
        guard turn?.state.editable == true else { return }
        actions?.dismiss()
        history?.selectConversation(id); turn?.select(history?.state.selected?.target)
    }

    func closeConversation() {
        guard turn?.state.editable == true else { return }
        actions?.dismiss()
        history?.closeConversation(); turn?.select(nil)
    }

    private func acceptTurn(_ state: ChatTurnState) {
        guard let account = state.account, history?.state.account == account,
              turn?.state.account == account else { return }
        if let pending = state.pending, turn?.state.pending == pending {
            history?.openConversation(pending.target)
        }
        if let receipt = state.receipt, turn?.state.receipt == receipt {
            if history?.state.selected == nil, turn?.state.target == receipt.pending.target {
                history?.openConversation(receipt.pending.target)
            }
            history?.accept(receipt, account: account)
            turn?.acknowledge(receipt)
        }
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
