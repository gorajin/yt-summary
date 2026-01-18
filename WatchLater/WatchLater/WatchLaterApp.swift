import SwiftUI

@main
struct WatchLaterApp: App {
    @StateObject private var authManager = AuthManager()
    
    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(authManager)
                .onOpenURL { url in
                    handleIncomingURL(url)
                }
        }
    }
    
    /// Handles incoming URLs for OAuth callbacks
    private func handleIncomingURL(_ url: URL) {
        // Check if this is an auth callback
        guard url.scheme == "watchlater",
              url.host == "auth" else {
            return
        }
        
        // Handle OAuth callback
        do {
            try authManager.handleOAuthCallback(url: url)
        } catch {
            print("OAuth callback error: \(error)")
        }
    }
}
