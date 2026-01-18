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
        do {
            let user = try await api.getProfile(authToken: token)
            isNotionConnected = user.notionConnected
            summariesRemaining = user.summariesRemaining
        } catch {
            print("Failed to load profile: \(error)")
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
