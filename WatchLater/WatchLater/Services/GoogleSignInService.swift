import Foundation
import AuthenticationServices
import SwiftUI

// MARK: - Google Sign-In Service

/// Handles Google OAuth flow using ASWebAuthenticationSession
/// This uses Supabase's OAuth provider flow, which manages the token exchange
@MainActor
class GoogleSignInService: NSObject, ObservableObject, ASWebAuthenticationPresentationContextProviding {
    
    private var webAuthSession: ASWebAuthenticationSession?
    private var continuation: CheckedContinuation<URL, Error>?
    
    // MARK: - Sign In with Google
    
    /// Initiates Google OAuth flow via Supabase
    /// Returns the callback URL containing access tokens
    func signIn() async throws -> URL {
        // Build the Supabase OAuth URL for Google
        var components = URLComponents(string: "\(APIConfig.supabaseURL)/auth/v1/authorize")!
        components.queryItems = [
            URLQueryItem(name: "provider", value: "google"),
            URLQueryItem(name: "redirect_to", value: "watchlater://auth/callback"),
            URLQueryItem(name: "scopes", value: "email profile")
        ]
        
        guard let authURL = components.url else {
            throw GoogleSignInError.invalidURL
        }
        
        return try await withCheckedThrowingContinuation { continuation in
            self.continuation = continuation
            
            let session = ASWebAuthenticationSession(
                url: authURL,
                callbackURLScheme: "watchlater"
            ) { [weak self] callbackURL, error in
                if let error = error {
                    if (error as NSError).code == ASWebAuthenticationSessionError.canceledLogin.rawValue {
                        self?.continuation?.resume(throwing: GoogleSignInError.cancelled)
                    } else {
                        self?.continuation?.resume(throwing: GoogleSignInError.authenticationFailed(error.localizedDescription))
                    }
                    return
                }
                
                guard let url = callbackURL else {
                    self?.continuation?.resume(throwing: GoogleSignInError.noCallback)
                    return
                }
                
                self?.continuation?.resume(returning: url)
            }
            
            session.presentationContextProvider = self
            session.prefersEphemeralWebBrowserSession = false
            
            self.webAuthSession = session
            session.start()
        }
    }
    
    // MARK: - Parse Callback
    
    /// Parses the OAuth callback URL to extract tokens
    static func parseCallback(url: URL) -> (accessToken: String?, refreshToken: String?, error: String?) {
        // Supabase returns tokens in the fragment (hash)
        // Format: watchlater://auth/callback#access_token=xxx&refresh_token=xxx&...
        
        guard let fragment = url.fragment else {
            // Check if error is in query params
            let components = URLComponents(url: url, resolvingAgainstBaseURL: false)
            let error = components?.queryItems?.first(where: { $0.name == "error_description" })?.value
            return (nil, nil, error ?? "No authentication data received")
        }
        
        // Parse fragment as query items
        var params: [String: String] = [:]
        let pairs = fragment.split(separator: "&")
        for pair in pairs {
            let keyValue = pair.split(separator: "=", maxSplits: 1)
            if keyValue.count == 2 {
                let key = String(keyValue[0])
                let value = String(keyValue[1]).removingPercentEncoding ?? String(keyValue[1])
                params[key] = value
            }
        }
        
        return (
            params["access_token"],
            params["refresh_token"],
            params["error_description"]
        )
    }
    
    // MARK: - ASWebAuthenticationPresentationContextProviding
    
    func presentationAnchor(for session: ASWebAuthenticationSession) -> ASPresentationAnchor {
        guard let scene = UIApplication.shared.connectedScenes.first as? UIWindowScene,
              let window = scene.windows.first else {
            return UIWindow()
        }
        return window
    }
}

// MARK: - Errors

enum GoogleSignInError: LocalizedError {
    case invalidURL
    case cancelled
    case noCallback
    case authenticationFailed(String)
    case noAccessToken
    
    var errorDescription: String? {
        switch self {
        case .invalidURL:
            return "Could not create authentication URL"
        case .cancelled:
            return "Sign in was cancelled"
        case .noCallback:
            return "No response from Google"
        case .authenticationFailed(let message):
            return message
        case .noAccessToken:
            return "No access token received"
        }
    }
}
