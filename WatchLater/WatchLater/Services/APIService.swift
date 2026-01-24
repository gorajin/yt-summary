import Foundation
import Combine
// MARK: - API Configuration
// Configuration is centralized in Config.swift (AppConfig)
// This file uses AppConfig for all endpoints and keys

// MARK: - API Service

class APIService {
    static let shared = APIService()
    private init() {}
    
    // MARK: - Summarize
    
    func summarize(url: String, authToken: String) async throws -> SummaryResponse {
        let endpoint = URL(string: "\(AppConfig.apiBaseURL)/summarize")!
        
        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"
        request.timeoutInterval = AppConfig.summarizeTimeout
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
        let endpoint = URL(string: "\(AppConfig.apiBaseURL)/me")!
        
        var request = URLRequest(url: endpoint)
        request.timeoutInterval = AppConfig.apiTimeout
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
        let endpoint = URL(string: "\(AppConfig.apiBaseURL)/auth/notion?user_id=\(userId)")!
        
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
