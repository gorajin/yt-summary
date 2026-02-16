//
//  Config.swift
//  WatchLater
//
//  Centralized configuration shared between main app and Share Extension.
//  This file should be added to both targets in Xcode.
//

import Foundation

/// Centralized configuration for the WatchLater app
enum AppConfig {
    // MARK: - API Endpoints
    
    /// Backend API base URL (Railway deployment)
    static let apiBaseURL = "https://watchlater.up.railway.app"
    
    // MARK: - Supabase Configuration
    
    /// Supabase project URL
    static let supabaseURL = "https://lnmlpwcntttemnisoxrf.supabase.co"
    
    /// Supabase anonymous key (safe to include in client - RLS enforced)
    static let supabaseAnonKey = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImxubWxwd2NudHR0ZW1uaXNveHJmIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjgxNjgxNjksImV4cCI6MjA4Mzc0NDE2OX0.onowpihNxyb_Z2JSxGuwLdVb_HF2NWmePN-9UW1fBJY"
    
    // MARK: - OAuth Configuration
    
    /// Google OAuth client ID for iOS
    static let googleClientID = "3801364532-kuk4v6v9949dl9d3lcosnbm5h19qj203.apps.googleusercontent.com"
    
    /// App bundle identifier
    static let bundleID = "com.watchlater.app"
    
    /// Supabase OAuth callback URL
    static var redirectURL: String {
        return "\(supabaseURL)/auth/v1/callback"
    }
    
    // MARK: - Keychain Keys
    
    enum KeychainKeys {
        static let accessToken = "supabase_access_token"
        static let refreshToken = "supabase_refresh_token"
        static let userId = "supabase_user_id"
    }
    
    // MARK: - UserDefaults Keys
    
    enum UserDefaultsKeys {
        static let email = "supabase_email"
    }
    
    // MARK: - Timeouts
    
    /// Timeout for API requests (seconds)
    static let apiTimeout: TimeInterval = 30
    
    /// Extended timeout for summarize requests (long videos)
    static let summarizeTimeout: TimeInterval = 120
}
