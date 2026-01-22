import Foundation
import SwiftUI

@MainActor
class HomeViewModel: ObservableObject {
    @Published var isNotionConnected = false
    @Published var isProcessing = false
    @Published var statusMessage: String?
    @Published var isSuccess = false
    @Published var summariesRemaining: Int?
    
    private let api = APIService.shared
    
    // MARK: - Load Profile
    
    func loadProfile(token: String) async {
        #if DEBUG
        // Debug: Test token with debug endpoint
        await debugToken(token: token)
        #endif
        
        do {
            let user = try await api.getProfile(authToken: token)
            isNotionConnected = user.notionConnected
            summariesRemaining = user.summariesRemaining
            print("Profile loaded: notionConnected=\(user.notionConnected)")
        } catch {
            print("Failed to load profile: \(error)")
        }
    }
    
    private func debugToken(token: String) async {
        let endpoint = URL(string: "https://watchlater.up.railway.app/debug/token")!
        var request = URLRequest(url: endpoint)
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        
        do {
            let (data, _) = try await URLSession.shared.data(for: request)
            if let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                print("🔍 DEBUG TOKEN RESULT: \(json)")
            }
        } catch {
            print("Debug token request failed: \(error)")
        }
    }
    
    // MARK: - Summarize
    
    func summarize(url: String, token: String) async {
        isProcessing = true
        statusMessage = nil
        isSuccess = false
        
        do {
            let response = try await api.summarize(url: url, authToken: token)
            
            if response.success {
                statusMessage = "✅ Saved: \(response.title ?? "Summary")"
                isSuccess = true
                summariesRemaining = response.remaining
            } else {
                statusMessage = response.error ?? "Unknown error"
                isSuccess = false
            }
        } catch {
            statusMessage = error.localizedDescription
            isSuccess = false
        }
        
        isProcessing = false
    }
    
    // MARK: - Notion OAuth
    
    func startNotionOAuth(userId: String) async {
        do {
            let authURL = try await api.getNotionAuthURL(userId: userId)
            await MainActor.run {
                UIApplication.shared.open(authURL)
            }
        } catch {
            statusMessage = "Failed to start Notion connection: \(error.localizedDescription)"
            isSuccess = false
        }
    }
}
