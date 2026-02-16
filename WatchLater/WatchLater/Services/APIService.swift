import Foundation
import Combine

// NOTE: All configuration is centralized in Config.swift (AppConfig enum)
// which is shared between the main app and Share Extension.

// MARK: - API Service

class APIService {
    static let shared = APIService()
    private init() {}
    
    // MARK: - Summarize (Async Polling Architecture)
    
    func summarize(url: String, transcript: String? = nil, authToken: String) async throws -> SummaryResponse {
        // Step 1: Initiate job (also returns remaining count from 202 response)
        let (jobId, remaining) = try await initiateJob(url: url, transcript: transcript, authToken: authToken)
        
        // Step 2: Poll for completion
        var response = try await pollJobStatus(jobId: jobId, authToken: authToken)
        // Merge remaining count from initial job creation response
        if response.remaining == nil {
            response = SummaryResponse(
                success: response.success,
                title: response.title,
                notionUrl: response.notionUrl,
                error: response.error,
                remaining: remaining
            )
        }
        return response
    }
    
    /// Initiate a summarization job and return job_id
    /// Initiate a summarization job and return (job_id, remaining_count)
    private func initiateJob(url: String, transcript: String?, authToken: String) async throws -> (String, Int?) {
        let endpoint = URL(string: "\(AppConfig.apiBaseURL)/summarize")!
        
        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"
        request.timeoutInterval = AppConfig.apiTimeout
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(authToken)", forHTTPHeaderField: "Authorization")
        
        var bodyDict: [String: String] = ["url": url]
        if let transcript = transcript {
            bodyDict["transcript"] = transcript
        }
        request.httpBody = try JSONSerialization.data(withJSONObject: bodyDict)
        
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
        
        if httpResponse.statusCode >= 400 {
            if let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let detail = json["detail"] as? String {
                throw APIError.serverError(detail)
            }
            throw APIError.serverError("Server error (\(httpResponse.statusCode))")
        }
        
        // Parse job_id and remaining from 202 response
        guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let jobId = json["job_id"] as? String else {
            throw APIError.serverError("Invalid job response")
        }
        
        let remaining = json["remaining"] as? Int
        
        print("API: Job created: \(jobId.prefix(8))... (remaining: \(remaining ?? -1))")
        return (jobId, remaining)
    }
    
    /// Poll job status until complete or failed (max 4 minutes)
    /// Resilient to network timeouts - long videos (4+ hours) may need 2-3 min server processing
    private func pollJobStatus(jobId: String, authToken: String, maxAttempts: Int = 80) async throws -> SummaryResponse {
        let statusURL = URL(string: "\(AppConfig.apiBaseURL)/status/\(jobId)")!
        var consecutiveNetworkErrors = 0
        let maxNetworkRetries = 15  // More tolerant of transient network issues
        
        for attempt in 1...maxAttempts {
            var request = URLRequest(url: statusURL)
            request.setValue("Bearer \(authToken)", forHTTPHeaderField: "Authorization")
            request.timeoutInterval = 30  // Generous timeout for Railway cold starts
            
            // Wrap in do-catch to handle network errors gracefully
            do {
                let (data, response) = try await URLSession.shared.data(for: request)
                consecutiveNetworkErrors = 0  // Reset on success
                
                guard let httpResponse = response as? HTTPURLResponse else {
                    try await Task.sleep(nanoseconds: 2_000_000_000)
                    continue
                }
                
                if httpResponse.statusCode == 401 {
                    throw APIError.unauthorized
                }
                
                if httpResponse.statusCode != 200 {
                    print("API: Poll \(attempt): HTTP \(httpResponse.statusCode)")
                    try await Task.sleep(nanoseconds: 2_000_000_000)
                    continue
                }
                
                guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                      let status = json["status"] as? String else {
                    print("API: Poll \(attempt): Invalid JSON response")
                    try await Task.sleep(nanoseconds: 2_000_000_000)
                    continue
                }
                
                let progress = json["progress"] as? Int ?? 0
                let stage = json["stage"] as? String ?? "Processing"
                print("API: Poll \(attempt): \(status) \(progress)% - \(stage)")
                
                if status == "complete" {
                    if let result = json["result"] as? [String: Any] {
                        return SummaryResponse(
                            success: result["success"] as? Bool ?? true,
                            title: result["title"] as? String,
                            notionUrl: result["notionUrl"] as? String,
                            error: nil,
                            remaining: nil
                        )
                    }
                    return SummaryResponse(success: true, title: "Summary saved!", notionUrl: nil, error: nil, remaining: nil)
                }
                
                if status == "failed" {
                    let error = json["error"] as? String ?? "Processing failed"
                    return SummaryResponse(success: false, title: nil, notionUrl: nil, error: error, remaining: nil)
                }
                
                // Wait 3 seconds before next poll
                try await Task.sleep(nanoseconds: 3_000_000_000)
                
            } catch {
                // Network error (timeout, connection refused, etc.)
                consecutiveNetworkErrors += 1
                print("API: Poll \(attempt): Network error (\(consecutiveNetworkErrors)/\(maxNetworkRetries)) - \(error.localizedDescription)")
                
                if consecutiveNetworkErrors >= maxNetworkRetries {
                    // Too many consecutive network errors - give up
                    throw APIError.networkError(error)
                }
                
                // Wait with exponential backoff before retry
                let backoffSeconds = UInt64(min(pow(2.0, Double(consecutiveNetworkErrors)), 8.0))
                try await Task.sleep(nanoseconds: backoffSeconds * 1_000_000_000)
                continue
            }
        }
        
        throw APIError.serverError("Processing timed out. Please try again.")
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
    
    // MARK: - Knowledge Map
    
    struct KnowledgeMapResponse: Codable {
        let knowledgeMap: KnowledgeMapData?
        let version: Int?
        let notionUrl: String?
        let updatedAt: String?
        let summaryCount: Int?
        let currentSummaryCount: Int?
        let isStale: Bool?
        let message: String?
    }
    
    struct KnowledgeMapData: Codable {
        let topics: [TopicData]?
        let connections: [TopicConnectionData]?
        let totalSummaries: Int?
        let version: Int?
    }
    
    struct TopicData: Codable, Identifiable {
        var id: String { name }
        let name: String
        let description: String
        let facts: [TopicFactData]?
        let relatedTopics: [String]?
        let videoIds: [String]?
        let importance: Int?
    }
    
    struct TopicFactData: Codable, Identifiable {
        var id: String { fact }
        let fact: String
        let sourceVideoId: String?
        let sourceTitle: String?
    }
    
    struct TopicConnectionData: Codable, Identifiable {
        var id: String { "\(from)_\(to)" }
        let from: String
        let to: String
        let relationship: String
    }
    
    func getKnowledgeMap(authToken: String) async throws -> KnowledgeMapResponse {
        let endpoint = URL(string: "\(AppConfig.apiBaseURL)/knowledge-map")!
        
        var request = URLRequest(url: endpoint)
        request.timeoutInterval = AppConfig.apiTimeout
        request.setValue("Bearer \(authToken)", forHTTPHeaderField: "Authorization")
        
        let (data, response) = try await URLSession.shared.data(for: request)
        
        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }
        
        if httpResponse.statusCode == 401 {
            throw APIError.unauthorized
        }
        
        if httpResponse.statusCode != 200 {
            throw APIError.serverError("Failed to fetch knowledge map (\(httpResponse.statusCode))")
        }
        
        return try JSONDecoder().decode(KnowledgeMapResponse.self, from: data)
    }
    
    struct BuildMapResponse: Codable {
        let jobId: String
        let message: String?
    }
    
    func buildKnowledgeMap(authToken: String) async throws -> BuildMapResponse {
        let endpoint = URL(string: "\(AppConfig.apiBaseURL)/knowledge-map/build")!
        
        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"
        request.timeoutInterval = AppConfig.apiTimeout
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(authToken)", forHTTPHeaderField: "Authorization")
        
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
        
        if httpResponse.statusCode >= 400 {
            if let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let detail = json["detail"] as? String {
                throw APIError.serverError(detail)
            }
            throw APIError.serverError("Server error (\(httpResponse.statusCode))")
        }
        
        return try JSONDecoder().decode(BuildMapResponse.self, from: data)
    }
}


// MARK: - Errors

enum APIError: LocalizedError {
    case invalidResponse
    case unauthorized
    case rateLimited
    case invalidURL
    case networkError(Error)
    case serverError(String)
    
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
        case .serverError(let message):
            return message
        }
    }
}
