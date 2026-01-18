import Foundation

struct User: Codable, Identifiable {
    let id: String
    let email: String
    var notionConnected: Bool
    var subscriptionTier: String
    var summariesThisMonth: Int
    var summariesRemaining: Int
    
    enum CodingKeys: String, CodingKey {
        case id
        case email
        case notionConnected = "notion_connected"
        case subscriptionTier = "subscription_tier"
        case summariesThisMonth = "summaries_this_month"
        case summariesRemaining = "summaries_remaining"
    }
}

struct SummaryResponse: Codable {
    let success: Bool
    let title: String?
    let notionUrl: String?
    let error: String?
    let remaining: Int?
}

struct AuthResponse: Codable {
    let accessToken: String
    let user: AuthUser
    
    enum CodingKeys: String, CodingKey {
        case accessToken = "access_token"
        case user
    }
}

struct AuthUser: Codable {
    let id: String
    let email: String?
}
