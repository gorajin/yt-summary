import SwiftUI

struct HomeView: View {
    @EnvironmentObject var authManager: AuthManager
    @StateObject private var viewModel = HomeViewModel()
    @State private var urlInput = ""
    @State private var showingSettings = false
    
    /// Extract video ID from YouTube URL
    private var videoId: String? {
        let patterns = [
            #"(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/shorts\/|youtube\.com\/live\/)([a-zA-Z0-9_-]{11})"#,
            #"(?:youtube\.com\/embed\/)([a-zA-Z0-9_-]{11})"#
        ]

        
        for pattern in patterns {
            if let regex = try? NSRegularExpression(pattern: pattern),
               let match = regex.firstMatch(in: urlInput, range: NSRange(urlInput.startIndex..., in: urlInput)),
               let range = Range(match.range(at: 1), in: urlInput) {
                return String(urlInput[range])
            }
        }
        return nil
    }
    
    /// YouTube thumbnail URL
    private var thumbnailURL: URL? {
        guard let videoId = videoId else { return nil }
        return URL(string: "https://img.youtube.com/vi/\(videoId)/mqdefault.jpg")
    }
    
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
                        
                        // Video Preview with Thumbnail (when URL is valid)
                        if let thumbnailURL = thumbnailURL {
                            HStack(spacing: 12) {
                                AsyncImage(url: thumbnailURL) { phase in
                                    switch phase {
                                    case .success(let image):
                                        image
                                            .resizable()
                                            .aspectRatio(16/9, contentMode: .fill)
                                            .frame(width: 100, height: 56)
                                            .cornerRadius(8)
                                    case .failure(_):
                                        thumbnailPlaceholder
                                    case .empty:
                                        thumbnailPlaceholder
                                            .overlay(ProgressView().tint(.gray))
                                    @unknown default:
                                        thumbnailPlaceholder
                                    }
                                }
                                
                                VStack(alignment: .leading, spacing: 4) {
                                    Text("YouTube Video")
                                        .font(.subheadline)
                                        .fontWeight(.medium)
                                    
                                    Text(urlInput)
                                        .lineLimit(1)
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                }
                                
                                Spacer()
                            }
                            .padding(.horizontal, 4)
                        }
                        
                        // Summarize Button with Progress UI
                        Button(action: summarize) {
                            if viewModel.isProcessing {
                                // Enhanced progress UI with stages
                                VStack(spacing: 10) {
                                    // Stage indicator with icon
                                    HStack(spacing: 8) {
                                        Image(systemName: viewModel.currentStage.icon)
                                            .font(.subheadline)
                                        Text(viewModel.currentStage.displayText)
                                            .font(.subheadline)
                                    }
                                    .foregroundStyle(.white)
                                    
                                    // Progress bar
                                    GeometryReader { geometry in
                                        ZStack(alignment: .leading) {
                                            // Background track
                                            RoundedRectangle(cornerRadius: 4)
                                                .fill(Color.white.opacity(0.3))
                                                .frame(height: 6)
                                            
                                            // Progress fill
                                            RoundedRectangle(cornerRadius: 4)
                                                .fill(Color.white)
                                                .frame(width: geometry.size.width * viewModel.overallProgress, height: 6)
                                                .animation(.linear(duration: 0.1), value: viewModel.overallProgress)
                                        }
                                    }
                                    .frame(height: 6)
                                }
                                .frame(maxWidth: .infinity)
                                .padding()
                            } else {
                                HStack {
                                    Image(systemName: "sparkles")
                                    Text("Summarize & Save")
                                }
                                .frame(maxWidth: .infinity)
                                .padding()
                            }
                        }
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
                // Refresh token first on appear, then load profile
                Task {
                    await authManager.refreshTokenIfNeeded()
                    if let token = authManager.accessToken {
                        await viewModel.loadProfile(token: token)
                    }
                }
            }
            .onChange(of: authManager.notionJustConnected) { _, connected in
                if connected {
                    authManager.notionJustConnected = false
                    // Refresh token first, then load profile with fresh token
                    Task {
                        await authManager.refreshTokenIfNeeded()
                        if let token = authManager.accessToken {
                            await viewModel.loadProfile(token: token)
                        }
                    }
                }
            }
        }
    }
    
    private var thumbnailPlaceholder: some View {
        Rectangle()
            .fill(Color(.systemGray5))
            .frame(width: 100, height: 56)
            .cornerRadius(8)
            .overlay(
                Image(systemName: "play.rectangle.fill")
                    .font(.title2)
                    .foregroundStyle(.red)
            )
    }
    
    private func loadProfile() {
        Task {
            if let token = authManager.accessToken {
                await viewModel.loadProfile(token: token)
            }
        }
    }
    
    private func connectNotion() {
        Task {
            await viewModel.startNotionOAuth(userId: authManager.userId ?? "")
        }
    }
    
    private func summarize() {
        // Haptic feedback
        let impactFeedback = UIImpactFeedbackGenerator(style: .medium)
        impactFeedback.impactOccurred()
        
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
