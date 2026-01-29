import SwiftUI

@main
struct WatchLaterApp: App {
    @StateObject private var authManager = AuthManager()
    @StateObject private var storeManager = StoreManager()
    @State private var shouldRefreshProfile = false
    
    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(authManager)
                .environmentObject(storeManager)
                .onOpenURL { url in
                    handleIncomingURL(url)
                }
                .onChange(of: shouldRefreshProfile) { _, newValue in
                    if newValue {
                        shouldRefreshProfile = false
                        // Profile refresh is handled by AuthManager
                    }
                }
        }
    }
    
    /// Handles incoming URLs for OAuth callbacks
    private func handleIncomingURL(_ url: URL) {
        guard url.scheme == "watchlater" else { return }
        
        // Handle Google OAuth callback
        if url.host == "auth" {
            do {
                try authManager.handleOAuthCallback(url: url)
            } catch {
                print("OAuth callback error: \(error)")
            }
        }
        
        // Handle Notion OAuth callback
        if url.host == "notion-connected" {
            let components = URLComponents(url: url, resolvingAgainstBaseURL: false)
            let success = components?.queryItems?.first(where: { $0.name == "success" })?.value == "true"
            
            if success {
                print("✓ Notion connected successfully!")
                // Trigger profile refresh
                authManager.notionJustConnected = true
            } else {
                let error = components?.queryItems?.first(where: { $0.name == "error" })?.value ?? "Unknown error"
                print("✗ Notion connection failed: \(error)")
            }
        }
    }
}
