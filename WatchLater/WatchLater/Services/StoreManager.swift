import Foundation
import StoreKit

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
            print("StoreKit: Loaded \(products.count) products")
        } catch {
            print("StoreKit: Failed to load products: \(error)")
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
                print("StoreKit: Purchase successful for \(product.id)")
                return true
                
            case .userCancelled:
                isLoading = false
                print("StoreKit: User cancelled purchase")
                return false
                
            case .pending:
                isLoading = false
                print("StoreKit: Purchase pending (e.g., parental approval)")
                errorMessage = "Purchase is pending approval"
                return false
                
            @unknown default:
                isLoading = false
                return false
            }
        } catch {
            isLoading = false
            errorMessage = "Purchase failed: \(error.localizedDescription)"
            print("StoreKit: Purchase error: \(error)")
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
        
        // Check current entitlements
        for await result in Transaction.currentEntitlements {
            do {
                let transaction = try checkVerified(result)
                
                // For subscriptions, check if still valid
                if transaction.productType == .autoRenewable {
                    purchased.insert(transaction.productID)
                }
            } catch {
                print("StoreKit: Failed to verify transaction: \(error)")
            }
        }
        
        purchasedProductIDs = purchased
        print("StoreKit: Current entitlements: \(purchased)")
        
        // Sync with backend
        if let productID = purchased.first {
            await syncSubscriptionWithBackend(productID: productID)
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
                    print("StoreKit: Transaction update failed: \(error)")
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
    
    private func syncSubscriptionWithBackend(productID: String) async {
        // TODO: Call backend to update user's subscription_tier
        // This ensures the backend knows about the subscription
        print("StoreKit: Should sync \(productID) with backend")
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
