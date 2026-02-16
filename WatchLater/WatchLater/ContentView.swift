import SwiftUI

// MARK: - Main Tab Container (Fix #2: HistoryView is now reachable)

struct ContentView: View {
    @EnvironmentObject var authManager: AuthManager
    @EnvironmentObject var storeManager: StoreManager
    
    var body: some View {
        Group {
            if authManager.isAuthenticated {
                MainTabView()
            } else {
                AuthView()
            }
        }
        .animation(.easeInOut, value: authManager.isAuthenticated)
    }
}

/// Tab bar with Home + History + Knowledge Map
struct MainTabView: View {
    @EnvironmentObject var storeManager: StoreManager
    
    var body: some View {
        TabView {
            HomeView()
                .tabItem {
                    Label("Home", systemImage: "house.fill")
                }
            
            HistoryView()
                .tabItem {
                    Label("History", systemImage: "clock.fill")
                }
            
            KnowledgeMapView()
                .tabItem {
                    Label("Knowledge", systemImage: "map.fill")
                }
        }
        .tint(.red)
    }
}

#Preview {
    ContentView()
        .environmentObject(AuthManager())
        .environmentObject(StoreManager())
}
