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
    
    // Timeouts
    static let apiTimeout: TimeInterval = 30
    static let summarizeTimeout: TimeInterval = 120
}

// MARK: - API Service

class APIService {
    static let shared = APIService()
    private init() {}
    
    // MARK: - Summarize (Async Polling Architecture)
    
    func summarize(url: String, transcript: String? = nil, authToken: String) async throws -> SummaryResponse {
        // Step 1: Initiate job
        let jobId = try await initiateJob(url: url, transcript: transcript, authToken: authToken)
        
        // Step 2: Poll for completion
        return try await pollJobStatus(jobId: jobId, authToken: authToken)
    }
    
    /// Initiate a summarization job and return job_id
    private func initiateJob(url: String, transcript: String?, authToken: String) async throws -> String {
        let endpoint = URL(string: "\(APIConfig.baseURL)/summarize")!
        
        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"
        request.timeoutInterval = APIConfig.apiTimeout
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
        
        // Parse job_id from 202 response
        guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let jobId = json["job_id"] as? String else {
            throw APIError.serverError("Invalid job response")
        }
        
        print("API: Job created: \(jobId.prefix(8))...")
        return jobId
    }
    
    /// Poll job status until complete or failed (max 2 minutes)
    private func pollJobStatus(jobId: String, authToken: String, maxAttempts: Int = 60) async throws -> SummaryResponse {
        let statusURL = URL(string: "\(APIConfig.baseURL)/status/\(jobId)")!
        
        for attempt in 1...maxAttempts {
            var request = URLRequest(url: statusURL)
            request.setValue("Bearer \(authToken)", forHTTPHeaderField: "Authorization")
            request.timeoutInterval = 10
            
            let (data, response) = try await URLSession.shared.data(for: request)
            
            guard let httpResponse = response as? HTTPURLResponse,
                  httpResponse.statusCode == 200 else {
                try await Task.sleep(nanoseconds: 2_000_000_000)  // 2s
                continue
            }
            
            guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let status = json["status"] as? String else {
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
            
            // Wait 2 seconds before next poll
            try await Task.sleep(nanoseconds: 2_000_000_000)
        }
        
        throw APIError.serverError("Processing timed out. Please try again.")
    }

    
    // MARK: - Get User Profile
    
    func getProfile(authToken: String) async throws -> User {
        let endpoint = URL(string: "\(APIConfig.baseURL)/me")!
        
        var request = URLRequest(url: endpoint)
        request.timeoutInterval = APIConfig.apiTimeout
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
