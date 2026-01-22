import Foundation
import Combine

// MARK: - API Configuration

enum APIConfig {
    static let baseURL = "https://watchlater.up.railway.app"
    static let supabaseURL = "https://lnmlpwcntttemnisoxrf.supabase.co"
    static let supabaseAnonKey = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImxubWxwd2NudHR0ZW1uaXNveHJmIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjgxNjgxNjksImV4cCI6MjA4Mzc0NDE2OX0.onowpihNxyb_Z2JSxGuwLdVb_HF2NWmePN-9UW1fBJY"
    
    // Google OAuth
    static let googleClientID = "3801364532-kuk4v6v9949dl9d3lcosnbm5h19qj203.apps.googleusercontent.com"
    static let bundleID = "com.watchlater.app"
    static let redirectURL = "\(supabaseURL)/auth/v1/callback"
}

// MARK: - API Service

class APIService {
    static let shared = APIService()
    private init() {}
    
    // MARK: - Summarize
    
    func summarize(url: String, authToken: String) async throws -> SummaryResponse {
        let endpoint = URL(string: "\(APIConfig.baseURL)/summarize")!
        
        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"
        request.timeoutInterval = 30
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(authToken)", forHTTPHeaderField: "Authorization")
        request.httpBody = try JSONEncoder().encode(["url": url])
        
        let (data, response) = try await URLSession.shared.data(for: request)
        
        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }
        
        if httpResponse.statusCode == 401 {
            throw APIError.unauthorized
        }
        
        if httpResponse.statusCode == 429 {
            throw APIError.rateLimited
        }
        
        return try JSONDecoder().decode(SummaryResponse.self, from: data)
    }
    
    // MARK: - Get User Profile
    
    func getProfile(authToken: String) async throws -> User {
        let endpoint = URL(string: "\(APIConfig.baseURL)/me")!
        
        var request = URLRequest(url: endpoint)
        request.timeoutInterval = 30
        request.setValue("Bearer \(authToken)", forHTTPHeaderField: "Authorization")
        
        let (data, response) = try await URLSession.shared.data(for: request)
        
        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }
        
        if httpResponse.statusCode == 401 {
            print("API: /me returned 401 - token invalid")
            throw APIError.unauthorized
        }
        
        if httpResponse.statusCode != 200 {
            print("API: /me returned \(httpResponse.statusCode)")
            throw APIError.invalidResponse
        }
        
        return try JSONDecoder().decode(User.self, from: data)
    }
    
    // MARK: - Start Notion OAuth
    
    func getNotionAuthURL(userId: String) async throws -> URL {
        let endpoint = URL(string: "\(APIConfig.baseURL)/auth/notion?user_id=\(userId)")!
        
        let (data, _) = try await URLSession.shared.data(from: endpoint)
        
        struct AuthURLResponse: Codable {
            let auth_url: String
        }
        
        let response = try JSONDecoder().decode(AuthURLResponse.self, from: data)
        guard let url = URL(string: response.auth_url) else {
            throw APIError.invalidURL
        }
        return url
    }
}

// MARK: - Errors

enum APIError: LocalizedError {
    case invalidResponse
    case unauthorized
    case rateLimited
    case invalidURL
    case networkError(Error)
    
    var errorDescription: String? {
        switch self {
        case .invalidResponse:
            return "Invalid server response"
        case .unauthorized:
            return "Please sign in again"
        case .rateLimited:
            return "Monthly limit reached. Upgrade to Pro for unlimited."
        case .invalidURL:
            return "Invalid URL"
        case .networkError(let error):
            return error.localizedDescription
        }
    }
}
