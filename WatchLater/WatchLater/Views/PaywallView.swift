import SwiftUI
import StoreKit

/// Paywall view for Pro subscription upgrade
struct PaywallView: View {
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject var storeManager: StoreManager
    
    @State private var selectedProduct: Product?
    @State private var isPurchasing = false
    @State private var showError = false
    @State private var errorMessage = ""
    @State private var showSuccess = false
    
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 24) {
                    // Header
                    headerSection
                    
                    // Features
                    featuresSection
                    
                    // Products
                    if storeManager.isLoading && storeManager.products.isEmpty {
                        ProgressView()
                            .padding(.top, 40)
                    } else {
                        productsSection
                    }
                    
                    // Restore
                    restoreButton
                    
                    // Terms
                    termsSection
                }
                .padding()
            }
            .navigationTitle("Go Pro")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Cancel") { dismiss() }
                }
            }
            .alert("Purchase Failed", isPresented: $showError) {
                Button("OK") { }
            } message: {
                Text(errorMessage)
            }
            .alert("Welcome to Pro! 🎉", isPresented: $showSuccess) {
                Button("Done") { dismiss() }
            } message: {
                Text("You now have unlimited summaries. Enjoy!")
            }
        }
    }
    
    // MARK: - Header
    
    private var headerSection: some View {
        VStack(spacing: 12) {
            Image(systemName: "star.circle.fill")
                .font(.system(size: 60))
                .foregroundStyle(.yellow)
            
            Text("Unlock Unlimited Summaries")
                .font(.title2.bold())
            
            Text("Save unlimited YouTube videos to Notion with AI-powered summaries")
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
        }
        .padding(.top, 20)
    }
    
    // MARK: - Features
    
    private var featuresSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            FeatureRow(icon: "infinity", title: "Unlimited Summaries", description: "No monthly limits")
            FeatureRow(icon: "bolt.fill", title: "Priority Processing", description: "Faster AI summarization")
            FeatureRow(icon: "heart.fill", title: "Support Development", description: "Help us build more features")
        }
        .padding()
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 16))
    }
    
    // MARK: - Products
    
    private var productsSection: some View {
        VStack(spacing: 12) {
            ForEach(storeManager.products, id: \.id) { product in
                ProductCard(
                    product: product,
                    isSelected: selectedProduct?.id == product.id,
                    isRecommended: product.id == StoreManager.proYearlyID
                ) {
                    selectedProduct = product
                }
            }
            
            // Purchase button
            Button {
                Task { await purchaseSelected() }
            } label: {
                HStack {
                    if isPurchasing {
                        ProgressView()
                            .tint(.white)
                    } else {
                        Text("Subscribe Now")
                            .fontWeight(.semibold)
                    }
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 16)
                .background(selectedProduct == nil ? Color.gray : Color.accentColor)
                .foregroundStyle(.white)
                .clipShape(RoundedRectangle(cornerRadius: 12))
            }
            .disabled(selectedProduct == nil || isPurchasing)
            .padding(.top, 8)
        }
    }
    
    // MARK: - Restore
    
    private var restoreButton: some View {
        Button("Restore Purchases") {
            Task {
                await storeManager.restorePurchases()
                if storeManager.isPro {
                    showSuccess = true
                }
            }
        }
        .font(.subheadline)
        .foregroundStyle(.secondary)
    }
    
    // MARK: - Terms
    
    private var termsSection: some View {
        VStack(spacing: 4) {
            Text("Subscription auto-renews unless cancelled at least 24 hours before the end of the current period.")
            Text("[Privacy Policy](https://gorajin.github.io/yt-summary/privacy.html) • [Terms of Use](https://gorajin.github.io/yt-summary/terms.html)")
        }
        .font(.caption2)
        .foregroundStyle(.secondary)
        .multilineTextAlignment(.center)
        .padding(.top, 8)
    }
    
    // MARK: - Actions
    
    private func purchaseSelected() async {
        guard let product = selectedProduct else { return }
        
        isPurchasing = true
        do {
            let success = try await storeManager.purchase(product)
            if success {
                showSuccess = true
            }
        } catch {
            errorMessage = error.localizedDescription
            showError = true
        }
        isPurchasing = false
    }
}

// MARK: - Feature Row

private struct FeatureRow: View {
    let icon: String
    let title: String
    let description: String
    
    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: icon)
                .font(.title3)
                .foregroundStyle(.accent)
                .frame(width: 32)
            
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.subheadline.bold())
                Text(description)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
    }
}

// MARK: - Product Card

private struct ProductCard: View {
    let product: Product
    let isSelected: Bool
    let isRecommended: Bool
    let onTap: () -> Void
    
    var body: some View {
        Button(action: onTap) {
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    HStack {
                        Text(product.displayName)
                            .font(.headline)
                        
                        if isRecommended {
                            Text("BEST VALUE")
                                .font(.caption2.bold())
                                .padding(.horizontal, 6)
                                .padding(.vertical, 2)
                                .background(.accent.opacity(0.2))
                                .foregroundStyle(.accent)
                                .clipShape(Capsule())
                        }
                    }
                    
                    Text(product.description)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                
                Spacer()
                
                VStack(alignment: .trailing, spacing: 2) {
                    Text(product.displayPrice)
                        .font(.headline)
                    Text(product.periodDescription)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            .padding()
            .background(
                RoundedRectangle(cornerRadius: 12)
                    .stroke(isSelected ? Color.accentColor : Color.gray.opacity(0.3), lineWidth: isSelected ? 2 : 1)
            )
            .background(
                isSelected ? Color.accentColor.opacity(0.05) : Color.clear,
                in: RoundedRectangle(cornerRadius: 12)
            )
        }
        .buttonStyle(.plain)
    }
}

#Preview {
    PaywallView()
        .environmentObject(StoreManager())
}
