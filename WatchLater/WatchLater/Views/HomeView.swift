import SwiftUI

struct HomeView: View {
    @EnvironmentObject var authManager: AuthManager
    @StateObject private var viewModel = HomeViewModel()
    @State private var urlInput = ""
    @State private var showingSettings = false
    
    var body: some View {
        NavigationStack {
            ZStack {
                // Background
                Color(.systemGroupedBackground)
                    .ignoresSafeArea()
                
                VStack(spacing: 24) {
                    // Notion Connection Status
                    if !viewModel.isNotionConnected {
                        NotionConnectionCard(onConnect: connectNotion)
                    }
                    
                    // URL Input Card
                    VStack(spacing: 16) {
                        HStack {
                            Image(systemName: "link")
                                .foregroundStyle(.secondary)
                            TextField("Paste YouTube URL", text: $urlInput)
                                .autocapitalization(.none)
                                .keyboardType(.URL)
                        }
                        .padding()
                        .background(.white)
                        .cornerRadius(12)
                        
                        Button(action: summarize) {
                            HStack {
                                if viewModel.isProcessing {
                                    ProgressView()
                                        .tint(.white)
                                } else {
                                    Image(systemName: "sparkles")
                                    Text("Summarize & Save")
                                }
                            }
                            .frame(maxWidth: .infinity)
                            .padding()
                            .background(
                                LinearGradient(
                                    colors: [.red, .orange],
                                    startPoint: .leading,
                                    endPoint: .trailing
                                )
                            )
                            .foregroundStyle(.white)
                            .fontWeight(.semibold)
                            .cornerRadius(12)
                        }
                        .disabled(urlInput.isEmpty || viewModel.isProcessing || !viewModel.isNotionConnected)
                    }
                    .padding()
                    .background(.white)
                    .cornerRadius(16)
                    .shadow(color: .black.opacity(0.05), radius: 10, y: 5)
                    .padding(.horizontal)
                    
                    // Status Message
                    if let status = viewModel.statusMessage {
                        HStack {
                            Image(systemName: viewModel.isSuccess ? "checkmark.circle.fill" : "exclamationmark.circle.fill")
                            Text(status)
                        }
                        .font(.subheadline)
                        .foregroundStyle(viewModel.isSuccess ? .green : .red)
                        .padding()
                        .background(viewModel.isSuccess ? Color.green.opacity(0.1) : Color.red.opacity(0.1))
                        .cornerRadius(12)
                        .padding(.horizontal)
                    }
                    
                    // Usage Stats
                    if let remaining = viewModel.summariesRemaining {
                        HStack {
                            Image(systemName: "chart.bar.fill")
                            Text(remaining < 0 ? "Unlimited summaries" : "\(remaining) summaries remaining this month")
                        }
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    }
                    
                    Spacer()
                }
                .padding(.top)
            }
            .navigationTitle("WatchLater")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button(action: { showingSettings = true }) {
                        Image(systemName: "gearshape.fill")
                    }
                }
            }
            .sheet(isPresented: $showingSettings) {
                SettingsView()
            }
            .onAppear {
                loadProfile()
            }
            .onChange(of: authManager.notionJustConnected) { _, connected in
                if connected {
                    authManager.notionJustConnected = false
                    // Refresh token first, then load profile
                    Task {
                        await authManager.refreshTokenIfNeeded()
                        loadProfile()
                    }
                }
            }
        }
    }
    
    private func loadProfile() {
        guard let token = authManager.accessToken else { return }
        Task {
            await viewModel.loadProfile(token: token)
        }
    }
    
    private func connectNotion() {
        Task {
            await viewModel.startNotionOAuth(userId: authManager.userId ?? "")
        }
    }
    
    private func summarize() {
        Task {
            await viewModel.summarize(url: urlInput, token: authManager.accessToken ?? "")
            if viewModel.isSuccess {
                urlInput = ""
            }
        }
    }
}

// MARK: - Supporting Views

struct NotionConnectionCard: View {
    let onConnect: () -> Void
    
    var body: some View {
        VStack(spacing: 12) {
            Image(systemName: "link.badge.plus")
                .font(.largeTitle)
                .foregroundStyle(.orange)
            
            Text("Connect Your Notion")
                .font(.headline)
            
            Text("Link your Notion workspace to save summaries")
                .font(.caption)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
            
            Button(action: onConnect) {
                Text("Connect Notion")
                    .fontWeight(.medium)
                    .padding(.horizontal, 24)
                    .padding(.vertical, 12)
                    .background(.orange)
                    .foregroundStyle(.white)
                    .cornerRadius(10)
            }
        }
        .padding(24)
        .frame(maxWidth: .infinity)
        .background(.white)
        .cornerRadius(16)
        .shadow(color: .black.opacity(0.05), radius: 10, y: 5)
        .padding(.horizontal)
    }
}

struct SettingsView: View {
    @EnvironmentObject var authManager: AuthManager
    @Environment(\.dismiss) var dismiss
    
    var body: some View {
        NavigationStack {
            List {
                Section("Account") {
                    HStack {
                        Text("Email")
                        Spacer()
                        Text(authManager.userEmail ?? "—")
                            .foregroundStyle(.secondary)
                    }
                }
                
                Section("Subscription") {
                    HStack {
                        Text("Plan")
                        Spacer()
                        Text("Free")
                            .foregroundStyle(.secondary)
                    }
                    
                    Button("Upgrade to Pro") {
                        // TODO: Show paywall
                    }
                }
                
                Section {
                    Button("Sign Out", role: .destructive) {
                        authManager.signOut()
                        dismiss()
                    }
                }
            }
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                }
            }
        }
    }
}

#Preview {
    HomeView()
        .environmentObject(AuthManager())
}
