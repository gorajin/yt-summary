import SwiftUI

// MARK: - Save Target

enum SaveTarget: String, CaseIterable {
    case notion = "notion"
    case obsidian = "obsidian"
    case appleNotes = "apple_notes"
    case files = "files"

    var displayName: String {
        switch self {
        case .notion: return "Notion"
        case .obsidian: return "Obsidian"
        case .appleNotes: return "Notes"
        case .files: return "Files"
        }
    }

    var icon: String {
        switch self {
        case .notion: return "n.square"
        case .obsidian: return "diamond"
        case .appleNotes: return "note.text"
        case .files: return "folder"
        }
    }

    /// Whether this target requires Notion to be connected
    var requiresNotion: Bool {
        self == .notion
    }
}

struct HomeView: View {
    @EnvironmentObject var authManager: AuthManager
    @EnvironmentObject var storeManager: StoreManager
    @StateObject private var viewModel = HomeViewModel()
    @State private var urlInput = ""
    @State private var showingSettings = false
    @State private var showingPaywall = false
    @State private var showingExportSheet = false

    @AppStorage("summaryFormat") private var summaryFormat: String = "detailed"
    @AppStorage("summaryLanguage") private var summaryLanguage: String = "en"
    @AppStorage("saveTarget") private var saveTargetRaw: String = "notion"

    private var saveTarget: SaveTarget {
        SaveTarget(rawValue: saveTargetRaw) ?? .notion
    }
    
    /// Extract video ID using shared logic (no more duplication)
    private var videoId: String? {
        TranscriptExtractor.extractVideoId(from: urlInput)
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
                    if viewModel.isLoadingProfile {
                        // Loading skeleton
                        VStack(spacing: 16) {
                            RoundedRectangle(cornerRadius: 12)
                                .fill(Color(.systemGray5))
                                .frame(height: 50)
                            
                            RoundedRectangle(cornerRadius: 12)
                                .fill(Color(.systemGray5))
                                .frame(height: 120)
                            
                            RoundedRectangle(cornerRadius: 12)
                                .fill(Color(.systemGray6))
                                .frame(height: 20)
                        }
                        .padding(.horizontal)
                        .redacted(reason: .placeholder)
                        .shimmer()
                    } else {
                    // Notion Connection Status (only shown when Notion is selected)
                    if saveTarget == .notion && !viewModel.isNotionConnected {
                        NotionConnectionCard(onConnect: connectNotion)
                    }
                    
                    // URL Input Card
                    VStack(spacing: 16) {
                        HStack {
                            Image(systemName: "link")
                                .foregroundStyle(.secondary)
                            TextField("Paste YouTube URL", text: $urlInput)
                                .autocapitalization(.none)
                                .autocorrectionDisabled(true)
                                .keyboardType(.URL)
                                
                            if !urlInput.isEmpty {
                                Button(action: { urlInput = "" }) {
                                    Image(systemName: "xmark.circle.fill")
                                        .foregroundStyle(.secondary)
                                }
                            } else {
                                Button(action: {
                                    if let string = UIPasteboard.general.string {
                                        urlInput = string
                                    }
                                }) {
                                    Text("Paste")
                                        .font(.subheadline)
                                        .fontWeight(.medium)
                                        .foregroundStyle(.red)
                                }
                            }
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
                            }
                            .padding(.horizontal, 4)
                            
                            // Configuration Options
                            HStack {
                                Menu {
                                    Picker("Format", selection: $summaryFormat) {
                                        Text("Detailed").tag("detailed")
                                        Text("Short").tag("short")
                                        Text("Actionable").tag("actionable")
                                    }
                                } label: {
                                    HStack(spacing: 4) {
                                        Image(systemName: "doc.text")
                                        Text(summaryFormat.capitalized)
                                        Image(systemName: "chevron.up.chevron.down")
                                            .font(.caption2)
                                    }
                                    .padding(.horizontal, 12)
                                    .padding(.vertical, 8)
                                    .background(Color(.systemGray6))
                                    .cornerRadius(8)
                                }

                                Menu {
                                    Picker("Language", selection: $summaryLanguage) {
                                        Text("English").tag("en")
                                        Text("Spanish").tag("es")
                                        Text("French").tag("fr")
                                        Text("German").tag("de")
                                        Text("Korean").tag("ko")
                                        Text("Japanese").tag("ja")
                                        Text("Chinese").tag("zh")
                                    }
                                } label: {
                                    HStack(spacing: 4) {
                                        Image(systemName: "globe")
                                        Text(languageDisplayName(for: summaryLanguage))
                                        Image(systemName: "chevron.up.chevron.down")
                                            .font(.caption2)
                                    }
                                    .padding(.horizontal, 12)
                                    .padding(.vertical, 8)
                                    .background(Color(.systemGray6))
                                    .cornerRadius(8)
                                }

                                Spacer()
                            }
                            .foregroundStyle(.primary)
                            .font(.subheadline)

                            // Save Target Picker
                            HStack(spacing: 0) {
                                ForEach(SaveTarget.allCases, id: \.rawValue) { target in
                                    Button(action: { saveTargetRaw = target.rawValue }) {
                                        VStack(spacing: 4) {
                                            Image(systemName: target.icon)
                                                .font(.system(size: 16))
                                            Text(target.displayName)
                                                .font(.caption2)
                                        }
                                        .frame(maxWidth: .infinity)
                                        .padding(.vertical, 8)
                                        .background(saveTarget == target ? Color.red.opacity(0.1) : Color.clear)
                                        .foregroundStyle(saveTarget == target ? .red : .secondary)
                                    }
                                }
                            }
                            .background(Color(.systemGray6))
                            .cornerRadius(10)
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
                        .disabled(urlInput.isEmpty || viewModel.isProcessing || (saveTarget.requiresNotion && !viewModel.isNotionConnected))
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
                    
                    // Usage Stats + Upgrade Prompt
                    if let remaining = viewModel.summariesRemaining {
                        HStack {
                            Image(systemName: "chart.bar.fill")
                            if remaining < 0 {
                                Text("Unlimited summaries")
                            } else if remaining <= 2 && remaining > 0 {
                                Text("⚠️ Only \(remaining) summar\(remaining == 1 ? "y" : "ies") left this month")
                                    .foregroundStyle(.orange)
                            } else {
                                Text("\(remaining) summaries remaining this month")
                            }
                            
                            // Show upgrade button for free users running low
                            if remaining >= 0 && !storeManager.isPro {
                                Spacer()
                                Button("Upgrade") {
                                    showingPaywall = true
                                }
                                .font(.caption.bold())
                                .foregroundStyle(.white)
                                .padding(.horizontal, 10)
                                .padding(.vertical, 4)
                                .background(.orange)
                                .clipShape(Capsule())
                            }
                        }
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .padding(.horizontal)
                    }
                    } // end else (loading skeleton)
                    
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
            .sheet(isPresented: $showingPaywall) {
                PaywallView()
            }
            .sheet(isPresented: $showingExportSheet) {
                if let exportContent = viewModel.lastExportContent {
                    ExportShareSheet(content: exportContent, saveTarget: saveTarget) {
                        showingExportSheet = false
                        urlInput = ""
                    }
                }
            }
            // Auto-present paywall when quota is exceeded (Fix #1)
            .onChange(of: viewModel.quotaExceeded) { _, exceeded in
                if exceeded {
                    showingPaywall = true
                    viewModel.quotaExceeded = false  // Reset for next time
                }
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
            await viewModel.summarize(
                url: urlInput,
                token: authManager.accessToken ?? "",
                summaryFormat: summaryFormat,
                language: summaryLanguage,
                saveTarget: saveTarget
            )
            if viewModel.isSuccess {
                // For non-Notion targets, show the export sheet
                if saveTarget != .notion, let exportContent = viewModel.lastExportContent {
                    showingExportSheet = true
                } else {
                    urlInput = ""
                }
            }
        }
    }
    
    private func languageDisplayName(for code: String) -> String {
        switch code {
        case "en": return "English"
        case "es": return "Spanish"
        case "fr": return "French"
        case "de": return "German"
        case "ko": return "Korean"
        case "ja": return "Japanese"
        case "zh": return "Chinese"
        default: return "English"
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
    @EnvironmentObject var storeManager: StoreManager
    @Environment(\.dismiss) var dismiss
    @State private var showingPaywall = false
    
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
                        if storeManager.isPro {
                            Text("Pro")
                                .foregroundStyle(.green)
                                .fontWeight(.medium)
                        } else {
                            Text("Free")
                                .foregroundStyle(.secondary)
                        }
                    }
                    
                    if !storeManager.isPro {
                        Button("Upgrade to Pro") {
                            showingPaywall = true
                        }
                    }
                }
                
                Section("About") {
                    HStack {
                        Text("Version")
                        Spacer()
                        Text(Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "—")
                            .foregroundStyle(.secondary)
                    }
                }
                
                Section {
                    Link("Privacy Policy", destination: URL(string: "https://gorajin.github.io/yt-summary/privacy.html")!)
                        .foregroundStyle(.primary)
                    Link("Terms of Use", destination: URL(string: "https://gorajin.github.io/yt-summary/terms.html")!)
                        .foregroundStyle(.primary)
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
            .sheet(isPresented: $showingPaywall) {
                PaywallView()
            }
        }
    }
}

#Preview {
    HomeView()
        .environmentObject(AuthManager())
        .environmentObject(StoreManager())
}

// MARK: - Shimmer Effect for Loading Skeleton

struct ShimmerModifier: ViewModifier {
    @State private var phase: CGFloat = 0
    
    func body(content: Content) -> some View {
        content
            .overlay(
                GeometryReader { geometry in
                    LinearGradient(
                        colors: [
                            .clear,
                            Color.primary.opacity(0.1),
                            .clear
                        ],
                        startPoint: .leading,
                        endPoint: .trailing
                    )
                    .frame(width: geometry.size.width * 0.6)
                    .offset(x: -geometry.size.width + (geometry.size.width * 1.6 * phase))
                }
                .clipped()
            )
            .onAppear {
                withAnimation(.linear(duration: 1.5).repeatForever(autoreverses: false)) {
                    phase = 1
                }
            }
    }
}

extension View {
    func shimmer() -> some View {
        modifier(ShimmerModifier())
    }
}

// MARK: - Export Share Sheet

struct ExportShareSheet: View {
    let content: HomeViewModel.ExportContent
    let saveTarget: SaveTarget
    let onDismiss: () -> Void

    @Environment(\.dismiss) var dismiss

    var body: some View {
        NavigationStack {
            VStack(spacing: 20) {
                Image(systemName: "checkmark.circle.fill")
                    .font(.system(size: 48))
                    .foregroundStyle(.green)

                Text("Summary Ready!")
                    .font(.title2)
                    .fontWeight(.bold)

                Text(content.title)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)

                VStack(spacing: 12) {
                    if saveTarget == .obsidian {
                        Button(action: openInObsidian) {
                            Label("Open in Obsidian", systemImage: "diamond")
                                .frame(maxWidth: .infinity)
                                .padding()
                                .background(.purple)
                                .foregroundStyle(.white)
                                .fontWeight(.semibold)
                                .cornerRadius(12)
                        }
                    }

                    Button(action: shareViaSheet) {
                        Label(
                            saveTarget == .appleNotes ? "Save to Notes" : "Save to Files",
                            systemImage: saveTarget == .appleNotes ? "note.text" : "folder"
                        )
                        .frame(maxWidth: .infinity)
                        .padding()
                        .background(.blue)
                        .foregroundStyle(.white)
                        .fontWeight(.semibold)
                        .cornerRadius(12)
                    }

                    Button(action: copyToClipboard) {
                        Label("Copy to Clipboard", systemImage: "doc.on.doc")
                            .frame(maxWidth: .infinity)
                            .padding()
                            .background(Color(.systemGray5))
                            .foregroundStyle(.primary)
                            .fontWeight(.medium)
                            .cornerRadius(12)
                    }
                }
                .padding(.horizontal)

                Spacer()
            }
            .padding(.top, 40)
            .navigationTitle("Export")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") {
                        onDismiss()
                        dismiss()
                    }
                }
            }
        }
    }

    private func openInObsidian() {
        // Obsidian URL scheme: obsidian://new?name=Title&content=...
        let name = content.filename.replacingOccurrences(of: ".md", with: "")
        var components = URLComponents()
        components.scheme = "obsidian"
        components.host = "new"
        components.queryItems = [
            URLQueryItem(name: "name", value: name),
            URLQueryItem(name: "content", value: content.text),
        ]
        if let url = components.url {
            UIApplication.shared.open(url)
        } else {
            // Fallback to share sheet
            shareViaSheet()
        }
    }

    private func shareViaSheet() {
        let activityItems: [Any]
        if saveTarget == .appleNotes {
            // Apple Notes handles HTML natively
            activityItems = [content.text]
        } else {
            // For Files: create a temporary file
            let tempURL = FileManager.default.temporaryDirectory.appendingPathComponent(content.filename)
            try? content.text.write(to: tempURL, atomically: true, encoding: .utf8)
            activityItems = [tempURL]
        }

        let activityVC = UIActivityViewController(activityItems: activityItems, applicationActivities: nil)

        if let windowScene = UIApplication.shared.connectedScenes.first as? UIWindowScene,
           let rootVC = windowScene.windows.first?.rootViewController {
            rootVC.present(activityVC, animated: true)
        }
    }

    private func copyToClipboard() {
        UIPasteboard.general.string = content.text
        onDismiss()
        dismiss()
    }
}
