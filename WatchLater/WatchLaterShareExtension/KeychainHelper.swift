import Foundation
import Security

/// Utility for secure storage of sensitive data in iOS Keychain
enum KeychainHelper {
    
    /// Service identifier for our app's keychain items
    private static let service = "com.watchlater.app"
    
    // MARK: - Save
    
    /// Save a string value to the Keychain
    /// - Parameters:
    ///   - value: The string to store
    ///   - key: The key to store it under
    ///   - accessGroup: Optional access group for sharing between app and extension
    static func save(_ value: String, forKey key: String, accessGroup: String? = "group.com.watchlater.app") {
        guard let data = value.data(using: .utf8) else { return }
        
        // Delete any existing item first
        delete(forKey: key, accessGroup: accessGroup)
        
        var query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key,
            kSecValueData as String: data,
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlock
        ]
        
        // Add access group for sharing with Share Extension
        if let accessGroup = accessGroup {
            query[kSecAttrAccessGroup as String] = accessGroup
        }
        
        let status = SecItemAdd(query as CFDictionary, nil)
        
        if status != errSecSuccess {
            print("Keychain save error for \(key): \(status)")
        }
    }
    
    // MARK: - Get
    
    /// Retrieve a string value from the Keychain
    /// - Parameters:
    ///   - key: The key to retrieve
    ///   - accessGroup: Optional access group for sharing between app and extension
    /// - Returns: The stored string, or nil if not found
    static func get(forKey key: String, accessGroup: String? = "group.com.watchlater.app") -> String? {
        var query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne
        ]
        
        if let accessGroup = accessGroup {
            query[kSecAttrAccessGroup as String] = accessGroup
        }
        
        var result: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        
        guard status == errSecSuccess,
              let data = result as? Data,
              let string = String(data: data, encoding: .utf8) else {
            return nil
        }
        
        return string
    }
    
    // MARK: - Delete
    
    /// Delete an item from the Keychain
    /// - Parameters:
    ///   - key: The key to delete
    ///   - accessGroup: Optional access group for sharing between app and extension
    static func delete(forKey key: String, accessGroup: String? = "group.com.watchlater.app") {
        var query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key
        ]
        
        if let accessGroup = accessGroup {
            query[kSecAttrAccessGroup as String] = accessGroup
        }
        
        SecItemDelete(query as CFDictionary)
    }
    
    // MARK: - Clear All
    
    /// Delete all keychain items for this service (used on sign out)
    static func clearAll() {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service
        ]
        
        SecItemDelete(query as CFDictionary)
    }
}
