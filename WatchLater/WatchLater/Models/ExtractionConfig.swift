//
//  ExtractionConfig.swift
//  WatchLater
//
//  Models for dynamic backend configuration of the transcript extraction logic.
//

import Foundation

struct ExtractionPattern: Codable {
    let name: String
    let pattern: String
    let description: String?
}

struct ExtractionConfig: Codable {
    let version: String
    let captionTrackPatterns: [ExtractionPattern]
    let userAgents: [String]
    
    enum CodingKeys: String, CodingKey {
        case version
        case captionTrackPatterns = "caption_track_patterns"
        case userAgents = "user_agents"
    }
    
    // MARK: - App Group Persistence
    
    static let sharedDefaults = UserDefaults(suiteName: "group.com.watchlater.app")
    private static let storageKey = "ExtractionConfigData"
    
    /// Save config to App Group UserDefaults
    func save() {
        if let data = try? JSONEncoder().encode(self) {
            ExtractionConfig.sharedDefaults?.set(data, forKey: ExtractionConfig.storageKey)
        }
    }
    
    /// Load config from App Group UserDefaults
    static func load() -> ExtractionConfig? {
        if let data = sharedDefaults?.data(forKey: storageKey),
           let config = try? JSONDecoder().decode(ExtractionConfig.self, from: data) {
            return config
        }
        return nil
    }
    
    // MARK: - Helper Accessors
    
    func pattern(for name: String) -> String? {
        return captionTrackPatterns.first { $0.name == name }?.pattern
    }
    
    var randomUserAgent: String? {
        return userAgents.randomElement()
    }
}
