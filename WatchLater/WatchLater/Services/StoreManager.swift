import Foundation
import StoreKit
import os.log

private let storeLog = OSLog(subsystem: "com.watchlater.app", category: "StoreManager")

/// Manages in-app purchases using StoreKit 2
@MainActor
class StoreManager: ObservableObject {
    
    // MARK: - Product IDs
    
    /// Product identifiers - must match App Store Connect
    static let proMonthlyID = "com.watchlater.app.pro.monthly"
    static let proYearlyID = "com.watchlater.app.pro.yearly"
    
    // MARK: - Published Properties
    
    @Published private(set) var products: [Product] = []
    @Published private(set) var purchasedProductIDs: Set<String> = []
    @Published private(set) var isLoading = false
    @Published private(set) var errorMessage: String?
    
    /// Whether user is a Pro subscriber
    var isPro: Bool {
        !purchasedProductIDs.isEmpty
    }
    
    // MARK: - Private
    
    private var updateListenerTask: Task<Void, Error>?
    
    // MARK: - Initialization
    
    init() {
        // Start listening for transaction updates
        updateListenerTask = listenForTransactions()
        
        // Load products and check status on init
        Task {
            await loadProducts()
            await updatePurchasedProducts()
        }
    }
    
    deinit {
        updateListenerTask?.cancel()
    }
    
    // MARK: - Load Products
    
    func loadProducts() async {
        isLoading = true
        errorMessage = nil
        
        do {
            let productIDs = [Self.proMonthlyID, Self.proYearlyID]
            products = try await Product.products(for: productIDs)
            products.sort { $0.price < $1.price }
            os_log("Loaded %d products", log: storeLog, type: .info, products.count)
        } catch {
            os_log("Failed to load products: %{public}@", log: storeLog, type: .error, "\(error)")
            errorMessage = "Failed to load subscription options"
        }
        
        isLoading = false
    }
    
    // MARK: - Purchase
    
    func purchase(_ product: Product) async throws -> Bool {
        isLoading = true
        errorMessage = nil
        
        do {
            let result = try await product.purchase()
            
            switch result {
            case .success(let verification):
                // Check whether the transaction is verified
                let transaction = try checkVerified(verification)
                
                // Update the purchased products
                await updatePurchasedProducts()
                
                // Finish the transaction
                await transaction.finish()
                
                isLoading = false
                os_log("Purchase successful for %{public}@", log: storeLog, type: .info, product.id)
                return true
                
            case .userCancelled:
                isLoading = false
                os_log("User cancelled purchase", log: storeLog, type: .info)
                return false
                
            case .pending:
                isLoading = false
                os_log("Purchase pending (e.g., parental approval)", log: storeLog, type: .info)
                errorMessage = "Purchase is pending approval"
                return false
                
            @unknown default:
                isLoading = false
                return false
            }
        } catch {
            isLoading = false
            errorMessage = "Purchase failed: \(error.localizedDescription)"
            os_log("Purchase error: %{public}@", log: storeLog, type: .error, "\(error)")
            throw error
        }
    }
    
    // MARK: - Restore Purchases
    
    func restorePurchases() async {
        isLoading = true
        errorMessage = nil
        
        do {
            // This will sync with the App Store
            try await AppStore.sync()
            await updatePurchasedProducts()
            
            if purchasedProductIDs.isEmpty {
                errorMessage = "No purchases to restore"
            }
        } catch {
            errorMessage = "Restore failed: \(error.localizedDescription)"
        }
        
        isLoading = false
    }
    
    // MARK: - Check Subscription Status
    
    func updatePurchasedProducts() async {
        var purchased: Set<String> = []
        var jwsRepresentations: [String: String] = [:]  // productID → JWS
        
        // Check current entitlements
        for await result in Transaction.currentEntitlements {
            do {
                let transaction = try checkVerified(result)
                
                // For subscriptions, check if still valid
                if transaction.productType == .autoRenewable {
                    purchased.insert(transaction.productID)
                    // Capture JWS representation for server-side verification
                    if case .verified(_) = result {
                        jwsRepresentations[transaction.productID] = result.jwsRepresentation
                    }
                }
            } catch {
                os_log("Failed to verify transaction: %{public}@", log: storeLog, type: .error, "\(error)")
            }
        }
        
        purchasedProductIDs = purchased
        os_log("Current entitlements: %{public}@", log: storeLog, type: .info, "\(purchased)")
        
        if let productID = purchased.first {
            // Active subscription: sync upgrade with JWS proof
            let jws = jwsRepresentations[productID]
            await syncSubscriptionWithBackend(productID: productID, signedTransaction: jws)
        } else {
            // No active subscription: sync downgrade
            await syncDowngradeWithBackend()
        }
    }
    
    // MARK: - Transaction Listener
    
    private func listenForTransactions() -> Task<Void, Error> {
        return Task.detached { [weak self] in
            // Listen for transaction updates (renewals, refunds, etc.)
            for await result in Transaction.updates {
                do {
                    let transaction = try await self?.checkVerified(result)
                    await self?.updatePurchasedProducts()
                    await transaction?.finish()
                } catch {
                    os_log("Transaction update failed: %{public}@", log: storeLog, type: .error, "\(error)")
                }
            }
        }
    }
    
    // MARK: - Helpers
    
    private func checkVerified<T>(_ result: VerificationResult<T>) throws -> T {
        switch result {
        case .unverified(_, let error):
            throw error
        case .verified(let safe):
            return safe
        }
    }
    
    private func syncSubscriptionWithBackend(productID: String, signedTransaction: String? = nil) async {
        // Get auth token from shared keychain
        guard let token = KeychainHelper.get(forKey: AppConfig.KeychainKeys.accessToken) else {
            os_log("No auth token for backend sync", log: storeLog, type: .error)
            return
        }
        
        guard let url = URL(string: "\(AppConfig.apiBaseURL)/subscription/sync") else { return }
        
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.timeoutInterval = AppConfig.apiTimeout
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        
        // Build request body
        var bodyDict: [String: String] = ["product_id": productID]
        
        // Include JWS signed transaction for server-side verification
        if let jws = signedTransaction {
            bodyDict["signed_transaction"] = jws
        }
        
        // Include original transaction ID
        for await result in Transaction.currentEntitlements {
            if case .verified(let transaction) = result,
               transaction.productID == productID {
                bodyDict["original_transaction_id"] = String(transaction.originalID)
                break
            }
        }
        
        do {
            request.httpBody = try JSONSerialization.data(withJSONObject: bodyDict)
            let (_, response) = try await URLSession.shared.data(for: request)
            
            if let httpResponse = response as? HTTPURLResponse {
                if httpResponse.statusCode == 200 {
                    os_log("Backend sync successful for %{public}@ (JWS: %{public}@)", log: storeLog, type: .info, productID, signedTransaction != nil ? "yes" : "no")
                } else {
                    os_log("Backend sync failed with status %d", log: storeLog, type: .error, httpResponse.statusCode)
                }
            }
        } catch {
            os_log("Backend sync error: %{public}@", log: storeLog, type: .error, error.localizedDescription)
        }
    }
    
    /// Notify backend that subscription has expired/been cancelled
    private func syncDowngradeWithBackend() async {
        guard let token = KeychainHelper.get(forKey: AppConfig.KeychainKeys.accessToken) else {
            os_log("No auth token for downgrade sync", log: storeLog, type: .error)
            return
        }
        
        guard let url = URL(string: "\(AppConfig.apiBaseURL)/subscription/downgrade") else { return }
        
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.timeoutInterval = AppConfig.apiTimeout
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            
            if let httpResponse = response as? HTTPURLResponse {
                if httpResponse.statusCode == 200 {
                    if let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                       let tier = json["subscription_tier"] as? String {
                        os_log("Downgrade sync complete - tier: %{public}@", log: storeLog, type: .info, tier)
                    } else {
                        os_log("Downgrade sync successful", log: storeLog, type: .info)
                    }
                } else {
                    os_log("Downgrade sync failed with status %d", log: storeLog, type: .error, httpResponse.statusCode)
                }
            }
        } catch {
            os_log("Downgrade sync error: %{public}@", log: storeLog, type: .error, error.localizedDescription)
        }
    }
}

// MARK: - Product Extensions

extension Product {
    /// Period description (e.g., "per month")
    var periodDescription: String {
        guard let subscription = subscription else { return "" }
        
        switch subscription.subscriptionPeriod.unit {
        case .day:
            return "per day"
        case .week:
            return "per week"
        case .month:
            return subscription.subscriptionPeriod.value == 1 ? "per month" : "every \(subscription.subscriptionPeriod.value) months"
        case .year:
            return subscription.subscriptionPeriod.value == 1 ? "per year" : "every \(subscription.subscriptionPeriod.value) years"
        @unknown default:
            return ""
        }
    }
}
