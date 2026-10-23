import SwiftUI

@main
struct SocraticMindApp: App {
    @StateObject private var model = AppModel()
    var body: some Scene {
        WindowGroup {
            AppRootView(model: model)
        }
    }
}
