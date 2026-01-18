import Foundation
import SwiftUI

// MARK: - Auth Manager

@MainActor
class AuthManager: ObservableObject {
    @Published var isAuthenticated = false
    @Published var userId: String?
    @Published var userEmail: String?
    @Published var accessToken: String?
    @Published var isGoogleSignInProgress = false
    @Published var notionJustConnected = false
    
    private let tokenKey = "supabase_access_token"
    private let userIdKey = "supabase_user_id"
    private let emailKey = "supabase_email"
    private let refreshTokenKey = "supabase_refresh_token"
    
    private let googleSignIn = GoogleSignInService()
    
    init() {
        loadStoredSession()
    }
    
    // MARK: - Sign Up
    
    func signUp(email: String, password: String) async throws {
        let url = URL(string: "\(APIConfig.supabaseURL)/auth/v1/signup")!
        
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue(APIConfig.supabaseAnonKey, forHTTPHeaderField: "apikey")
        
        let body = ["email": email, "password": password]
        request.httpBody = try JSONEncoder().encode(body)
        
        let (data, response) = try await URLSession.shared.data(for: request)
        
        guard let httpResponse = response as? HTTPURLResponse else {
            throw AuthError.invalidResponse
        }
        
        if httpResponse.statusCode >= 400 {
            if let errorResponse = try? JSONDecoder().decode(SupabaseError.self, from: data) {
                throw AuthError.serverError(errorResponse.message ?? "Sign up failed")
            }
            throw AuthError.serverError("Sign up failed")
        }
        
        let authResponse = try JSONDecoder().decode(SupabaseAuthResponse.self, from: data)
        
        if let token = authResponse.access_token {
            saveSession(token: token, refreshToken: authResponse.refresh_token, userId: authResponse.user?.id ?? "", email: email)
        }
    }
    
    // MARK: - Sign In
    
    func signIn(email: String, password: String) async throws {
        let url = URL(string: "\(APIConfig.supabaseURL)/auth/v1/token?grant_type=password")!
        
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue(APIConfig.supabaseAnonKey, forHTTPHeaderField: "apikey")
        
        let body = ["email": email, "password": password]
        request.httpBody = try JSONEncoder().encode(body)
        
        let (data, response) = try await URLSession.shared.data(for: request)
        
        guard let httpResponse = response as? HTTPURLResponse else {
            throw AuthError.invalidResponse
        }
        
        if httpResponse.statusCode >= 400 {
            if let errorResponse = try? JSONDecoder().decode(SupabaseError.self, from: data) {
                throw AuthError.serverError(errorResponse.message ?? errorResponse.error ?? "Sign in failed")
            }
            throw AuthError.serverError("Invalid email or password")
        }
        
        let authResponse = try JSONDecoder().decode(SupabaseAuthResponse.self, from: data)
        
        guard let token = authResponse.access_token else {
            throw AuthError.serverError("No access token received")
        }
        
        saveSession(token: token, refreshToken: authResponse.refresh_token, userId: authResponse.user?.id ?? "", email: email)
    }
    
    // MARK: - Sign In with Google
    
    func signInWithGoogle() async throws {
        isGoogleSignInProgress = true
        defer { isGoogleSignInProgress = false }
        
        let callbackURL = try await googleSignIn.signIn()
        try handleOAuthCallback(url: callbackURL)
    }
    
    /// Handles OAuth callback URL from Google Sign-In
    func handleOAuthCallback(url: URL) throws {
        let result = GoogleSignInService.parseCallback(url: url)
        
        if let error = result.error {
            throw AuthError.serverError(error)
        }
        
        guard let accessToken = result.accessToken else {
            throw AuthError.serverError("No access token received from Google")
        }
        
        // Fetch user info from Supabase using the token
        Task {
            do {
                let userInfo = try await fetchUserInfo(token: accessToken)
                saveSession(
                    token: accessToken,
                    refreshToken: result.refreshToken,
                    userId: userInfo.id,
                    email: userInfo.email ?? "Google User"
                )
            } catch {
                print("Failed to fetch user info: \(error)")
                // Still save session with minimal info
                saveSession(token: accessToken, refreshToken: result.refreshToken, userId: "", email: "Google User")
            }
        }
    }
    
    /// Fetches user info from Supabase using access token
    private func fetchUserInfo(token: String) async throws -> SupabaseUser {
        let url = URL(string: "\(APIConfig.supabaseURL)/auth/v1/user")!
        
        var request = URLRequest(url: url)
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue(APIConfig.supabaseAnonKey, forHTTPHeaderField: "apikey")
        
        let (data, _) = try await URLSession.shared.data(for: request)
        return try JSONDecoder().decode(SupabaseUser.self, from: data)
    }
    
    // MARK: - Sign Out
    
    func signOut() {
        UserDefaults.standard.removeObject(forKey: tokenKey)
        UserDefaults.standard.removeObject(forKey: userIdKey)
        UserDefaults.standard.removeObject(forKey: emailKey)
        UserDefaults.standard.removeObject(forKey: refreshTokenKey)
        
        isAuthenticated = false
        accessToken = nil
        userId = nil
        userEmail = nil
    }
    
    // MARK: - Session Management
    
    private func saveSession(token: String, refreshToken: String?, userId: String, email: String) {
        UserDefaults.standard.set(token, forKey: tokenKey)
        UserDefaults.standard.set(userId, forKey: userIdKey)
        UserDefaults.standard.set(email, forKey: emailKey)
        if let refreshToken = refreshToken {
            UserDefaults.standard.set(refreshToken, forKey: refreshTokenKey)
        }
        
        self.accessToken = token
        self.userId = userId
        self.userEmail = email
        self.isAuthenticated = true
    }
    
    private func loadStoredSession() {
        if let token = UserDefaults.standard.string(forKey: tokenKey),
           let userId = UserDefaults.standard.string(forKey: userIdKey) {
            self.accessToken = token
            self.userId = userId
            self.userEmail = UserDefaults.standard.string(forKey: emailKey)
            self.isAuthenticated = true
        }
    }
}

// MARK: - Supporting Types

struct SupabaseAuthResponse: Codable {
    let access_token: String?
    let refresh_token: String?
    let user: SupabaseUser?
}

struct SupabaseUser: Codable {
    let id: String
    let email: String?
}

struct SupabaseError: Codable {
    let error: String?
    let message: String?
    let error_description: String?
}

enum AuthError: LocalizedError {
    case invalidResponse
    case serverError(String)
    
    var errorDescription: String? {
        switch self {
        case .invalidResponse:
            return "Invalid response from server"
        case .serverError(let message):
            return message
        }
    }
}
