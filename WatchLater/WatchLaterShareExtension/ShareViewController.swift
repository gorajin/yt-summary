import UIKit
import SwiftUI

class ShareViewController: UIViewController {
    
    private let transcriptExtractor = TranscriptExtractor(logPrefix: "📱 Share:")
    
    override func viewDidLoad() {
        super.viewDidLoad()
        
        // Extract the shared URL
        extractSharedURL { [weak self] url in
            guard let self = self, let url = url else {
                self?.showError("Could not get URL")
                return
            }
            
            // Show the share UI
            self.showShareUI(url: url)
        }
    }
    
    private func extractSharedURL(completion: @escaping (String?) -> Void) {
        guard let extensionItem = extensionContext?.inputItems.first as? NSExtensionItem,
              let attachments = extensionItem.attachments else {
            completion(nil)
            return
        }
        
        // Try to get URL
        for attachment in attachments {
            if attachment.hasItemConformingToTypeIdentifier("public.url") {
                attachment.loadItem(forTypeIdentifier: "public.url", options: nil) { item, error in
                    DispatchQueue.main.async {
                        if let url = item as? URL {
                            completion(url.absoluteString)
                        } else {
                            completion(nil)
                        }
                    }
                }
                return
            }
            
            // Also try plain text (YouTube sometimes shares as text)
            if attachment.hasItemConformingToTypeIdentifier("public.plain-text") {
                attachment.loadItem(forTypeIdentifier: "public.plain-text", options: nil) { item, error in
                    DispatchQueue.main.async {
                        if let text = item as? String, text.contains("youtu") {
                            completion(text)
                        } else {
                            completion(nil)
                        }
                    }
                }
                return
            }
        }
        
        completion(nil)
    }
    
    private func showShareUI(url: String) {
        // Check if user is authenticated (read from shared Keychain)
        guard let token = KeychainHelper.get(forKey: "supabase_access_token") else {
            showError("Please sign in to WatchLater first")
            return
        }
        
        // Create SwiftUI view
        let shareView = ShareExtensionView(
            url: url,
            onSave: { [weak self] in
                self?.summarizeAndSave(url: url, token: token)
            },
            onCancel: { [weak self] in
                self?.extensionContext?.completeRequest(returningItems: nil, completionHandler: nil)
            }
        )
        
        let hostingController = UIHostingController(rootView: shareView)
        hostingController.view.backgroundColor = .clear
        
        addChild(hostingController)
        view.addSubview(hostingController.view)
        hostingController.view.translatesAutoresizingMaskIntoConstraints = false
        
        NSLayoutConstraint.activate([
            hostingController.view.topAnchor.constraint(equalTo: view.topAnchor),
            hostingController.view.bottomAnchor.constraint(equalTo: view.bottomAnchor),
            hostingController.view.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            hostingController.view.trailingAnchor.constraint(equalTo: view.trailingAnchor)
        ])
        
        hostingController.didMove(toParent: self)
    }
    
    private func summarizeAndSave(url: String, token: String) {
        Task {
            do {
                // Try client-side transcript extraction first (bypasses YouTube IP blocking)
                var transcript = await transcriptExtractor.fetchTranscript(for: url)
                
                // If client-side fails, signal server to attempt extraction
                if transcript == nil || transcript!.isEmpty {
                    print("📱 Share: Client-side transcript failed, requesting server extraction")
                    transcript = "__SERVER_EXTRACT__"
                    
                    await MainActor.run {
                        NotificationCenter.default.post(
                            name: NSNotification.Name("ServerFallbackMode"),
                            object: nil
                        )
                    }
                }
                
                // Initiate job and get jobId (async polling architecture)
                let jobId = try await initiateJobWithTokenRefresh(url: url, token: token, transcript: transcript ?? "")
                
                // Poll for completion
                let result = try await pollJobStatus(jobId: jobId, token: token)
                
                await MainActor.run {
                    if result.success {
                        self.showSuccess(title: result.title ?? "Summary saved!")
                    } else {
                        self.showError(result.error ?? "Failed to save")
                    }
                }
            } catch {
                await MainActor.run {
                    self.showError(error.localizedDescription)
                }
            }
        }
    }
    
    /// Initiates a summarization job with automatic retry on token expiry
    private func initiateJobWithTokenRefresh(url: String, token: String, transcript: String) async throws -> String {
        do {
            return try await initiateJob(url: url, token: token, transcript: transcript)
        } catch let error as NSError where error.code == 401 {
            print("📱 Share: Token expired, attempting refresh...")
            
            guard let refreshToken = KeychainHelper.get(forKey: "supabase_refresh_token") else {
                print("📱 Share: No refresh token available")
                throw error
            }
            
            guard let newToken = await refreshAccessToken(refreshToken: refreshToken) else {
                print("📱 Share: Token refresh failed")
                throw error
            }
            
            print("📱 Share: Token refreshed successfully, retrying...")
            return try await initiateJob(url: url, token: newToken, transcript: transcript)
        }
    }
    
    /// Initiate a summarization job and return jobId
    private func initiateJob(url: String, token: String, transcript: String) async throws -> String {
        let endpoint = URL(string: "\(AppConfig.apiBaseURL)/summarize")!
        
        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.timeoutInterval = AppConfig.apiTimeout
        
        let bodyDict: [String: String] = ["url": url, "transcript": transcript]
        request.httpBody = try JSONSerialization.data(withJSONObject: bodyDict)
        
        let (data, response) = try await URLSession.shared.data(for: request)
        
        guard let httpResponse = response as? HTTPURLResponse else {
            throw NSError(domain: "WatchLater", code: 0,
                userInfo: [NSLocalizedDescriptionKey: "Invalid server response"])
        }
        
        print("📱 Share: Initiate job response: \(httpResponse.statusCode)")
        
        if httpResponse.statusCode == 401 {
            throw NSError(domain: "WatchLater", code: 401,
                userInfo: [NSLocalizedDescriptionKey: "Please sign in first"])
        }
        
        if httpResponse.statusCode == 429 {
            throw NSError(domain: "WatchLater", code: 429,
                userInfo: [NSLocalizedDescriptionKey: "Monthly limit reached. Open WatchLater to upgrade to Pro for unlimited summaries."])
        }
        
        if httpResponse.statusCode >= 400 {
            if let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let detail = json["detail"] as? String {
                throw NSError(domain: "WatchLater", code: httpResponse.statusCode,
                    userInfo: [NSLocalizedDescriptionKey: detail])
            }
            throw NSError(domain: "WatchLater", code: httpResponse.statusCode,
                userInfo: [NSLocalizedDescriptionKey: "Server error"])
        }
        
        // Parse job_id from 202 response
        guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let jobId = json["job_id"] as? String else {
            throw NSError(domain: "WatchLater", code: 0,
                userInfo: [NSLocalizedDescriptionKey: "Invalid job response"])
        }
        
        print("📱 Share: Job created: \(jobId.prefix(8))...")
        return jobId
    }
    
    /// Poll job status until complete or failed
    /// Extended timeout (180 attempts × 2s = 6 min) to handle long video chunked processing
    private func pollJobStatus(jobId: String, token: String, maxAttempts: Int = 180) async throws -> SummarizeResult {
        let statusURL = URL(string: "\(AppConfig.apiBaseURL)/status/\(jobId)")!
        var consecutiveNetworkErrors = 0
        let maxNetworkRetries = 15
        
        for attempt in 1...maxAttempts {
            var request = URLRequest(url: statusURL)
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
            request.timeoutInterval = AppConfig.apiTimeout
            
            do {
                let (data, response) = try await URLSession.shared.data(for: request)
                consecutiveNetworkErrors = 0
                
                guard let httpResponse = response as? HTTPURLResponse,
                      httpResponse.statusCode == 200 else {
                    try await Task.sleep(nanoseconds: 2_000_000_000)
                    continue
                }
                
                guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                      let status = json["status"] as? String,
                      let progress = json["progress"] as? Int else {
                    try await Task.sleep(nanoseconds: 2_000_000_000)
                    continue
                }
                
                let stage = json["stage"] as? String ?? "Processing"
                print("📱 Share: Poll \(attempt): \(status) \(progress)% - \(stage)")
                
                // Update UI progress based on real server progress
                await MainActor.run {
                    NotificationCenter.default.post(
                        name: NSNotification.Name("UpdateServerProgress"),
                        object: nil,
                        userInfo: ["progress": progress, "stage": stage]
                    )
                }
                
                if status == "complete" {
                    if let result = json["result"] as? [String: Any] {
                        return SummarizeResult(
                            success: result["success"] as? Bool ?? true,
                            title: result["title"] as? String,
                            notionUrl: result["notionUrl"] as? String,
                            error: nil,
                            remaining: nil
                        )
                    }
                    return SummarizeResult(success: true, title: "Summary saved!", notionUrl: nil, error: nil, remaining: nil)
                }
                
                if status == "failed" {
                    let error = json["error"] as? String ?? "Processing failed"
                    return SummarizeResult(success: false, title: nil, notionUrl: nil, error: error, remaining: nil)
                }
                
                try await Task.sleep(nanoseconds: 2_000_000_000)
                
            } catch {
                consecutiveNetworkErrors += 1
                print("📱 Share: Poll \(attempt): Network error (\(consecutiveNetworkErrors)/\(maxNetworkRetries)) - \(error.localizedDescription)")
                
                if consecutiveNetworkErrors >= maxNetworkRetries {
                    throw NSError(domain: "WatchLater", code: -1001,
                        userInfo: [NSLocalizedDescriptionKey: "Network connection issues. Please check your internet and try again."])
                }
                
                let backoffSeconds = UInt64(min(pow(2.0, Double(consecutiveNetworkErrors)), 8.0))
                try await Task.sleep(nanoseconds: backoffSeconds * 1_000_000_000)
                continue
            }
        }
        
        throw NSError(domain: "WatchLater", code: 0,
            userInfo: [NSLocalizedDescriptionKey: "Processing timed out. This may happen with videos that have restricted captions. Please try a different video."])
    }
    
    /// Refresh an expired access token using Supabase
    private func refreshAccessToken(refreshToken: String) async -> String? {
        guard let url = URL(string: "\(AppConfig.supabaseURL)/auth/v1/token?grant_type=refresh_token") else {
            return nil
        }
        
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue(AppConfig.supabaseAnonKey, forHTTPHeaderField: "apikey")
        request.timeoutInterval = 15
        
        let body = ["refresh_token": refreshToken]
        request.httpBody = try? JSONSerialization.data(withJSONObject: body)
        
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            
            guard let httpResponse = response as? HTTPURLResponse, httpResponse.statusCode == 200 else {
                return nil
            }
            
            guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let accessToken = json["access_token"] as? String else {
                return nil
            }
            
            // Save the new tokens to Keychain for future use
            KeychainHelper.save(accessToken, forKey: "supabase_access_token")
            if let newRefreshToken = json["refresh_token"] as? String {
                KeychainHelper.save(newRefreshToken, forKey: "supabase_refresh_token")
            }
            
            print("📱 Share: ✅ Token refreshed and saved")
            return accessToken
        } catch {
            print("📱 Share: Token refresh network error: \(error)")
            return nil
        }
    }
    
    private func showSuccess(title: String) {
        NotificationCenter.default.post(name: NSNotification.Name("StopProgressTimer"), object: nil)
        
        let alert = UIAlertController(title: "✅ Saved!", message: title, preferredStyle: .alert)
        alert.addAction(UIAlertAction(title: "Done", style: .default) { [weak self] _ in
            self?.extensionContext?.completeRequest(returningItems: nil, completionHandler: nil)
        })
        present(alert, animated: true)
    }
    
    private func showError(_ message: String) {
        NotificationCenter.default.post(name: NSNotification.Name("StopProgressTimer"), object: nil)
        
        let alert = UIAlertController(title: "Error", message: message, preferredStyle: .alert)
        alert.addAction(UIAlertAction(title: "OK", style: .cancel) { [weak self] _ in
            self?.extensionContext?.cancelRequest(withError: NSError(domain: "WatchLater", code: 1))
        })
        present(alert, animated: true)
    }
}


// SummarizationStage is defined in the shared SummarizationStage.swift file

// MARK: - SwiftUI Share View

struct ShareExtensionView: View {
    let url: String
    let onSave: () -> Void
    let onCancel: () -> Void
    
    @State private var isLoading = false
    @State private var currentStage: SummarizationStage = .fetchingTranscript
    @State private var stageProgress: Double = 0.0
    @State private var progressTimer: Timer? = nil
    
    private static let extractor = TranscriptExtractor()
    
    /// Computed property for overall progress (0.0 - 1.0)
    private var overallProgress: Double {
        let stages = SummarizationStage.allCases
        guard let currentIndex = stages.firstIndex(of: currentStage) else { return 0 }
        
        let completedStages = Double(currentIndex)
        let totalStages = Double(stages.count)
        
        return (completedStages + stageProgress) / totalStages
    }
    
    /// Extract video ID from YouTube URL
    private var videoId: String? {
        Self.extractor.extractVideoId(from: url)
    }
    
    /// YouTube thumbnail URL
    private var thumbnailURL: URL? {
        guard let videoId = videoId else { return nil }
        return URL(string: "https://img.youtube.com/vi/\(videoId)/mqdefault.jpg")
    }
    
    var body: some View {
        VStack(spacing: 0) {
            Spacer()
            
            VStack(spacing: 20) {
                // Header
                HStack {
                    Button("Cancel") {
                        onCancel()
                    }
                    .foregroundStyle(.secondary)
                    
                    Spacer()
                    
                    Text("WatchLater")
                        .font(.headline)
                    
                    Spacer()
                    
                    Button("Cancel") {
                        onCancel()
                    }
                    .opacity(0) // Balance the header
                }
                .padding(.horizontal)
                
                // Video Preview with Thumbnail
                HStack(spacing: 12) {
                    if let thumbnailURL = thumbnailURL {
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
                    } else {
                        thumbnailPlaceholder
                    }
                    
                    VStack(alignment: .leading, spacing: 4) {
                        Text("YouTube Video")
                            .font(.subheadline)
                            .fontWeight(.medium)
                        
                        Text(url)
                            .lineLimit(1)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    
                    Spacer()
                }
                .padding()
                .background(Color(.systemGray6))
                .cornerRadius(12)
                .padding(.horizontal)
                
                // Save Button
                Button(action: {
                    let impactFeedback = UIImpactFeedbackGenerator(style: .medium)
                    impactFeedback.impactOccurred()
                    
                    isLoading = true
                    startProgressSimulation()
                    onSave()
                }) {
                    if isLoading {
                        VStack(spacing: 10) {
                            HStack(spacing: 8) {
                                Image(systemName: currentStage.icon)
                                    .font(.subheadline)
                                Text(currentStage.displayText)
                                    .font(.subheadline)
                            }
                            .foregroundStyle(.white)
                            
                            GeometryReader { geometry in
                                ZStack(alignment: .leading) {
                                    RoundedRectangle(cornerRadius: 4)
                                        .fill(Color.white.opacity(0.3))
                                        .frame(height: 6)
                                    
                                    RoundedRectangle(cornerRadius: 4)
                                        .fill(Color.white)
                                        .frame(width: geometry.size.width * overallProgress, height: 6)
                                        .animation(.linear(duration: 0.1), value: overallProgress)
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
                .disabled(isLoading)
                .padding(.horizontal)
                .padding(.bottom, 20)
            }
            .padding(.vertical, 20)
            .background(Color(.systemBackground))
            .cornerRadius(20, corners: [.topLeft, .topRight])
        }
        .background(Color.black.opacity(0.3))
        .onReceive(NotificationCenter.default.publisher(for: NSNotification.Name("StopProgressTimer"))) { _ in
            progressTimer?.invalidate()
            progressTimer = nil
        }
        .onReceive(NotificationCenter.default.publisher(for: NSNotification.Name("UpdateServerProgress"))) { notification in
            if let userInfo = notification.userInfo,
               let serverProgress = userInfo["progress"] as? Int,
               let stage = userInfo["stage"] as? String {
                
                progressTimer?.invalidate()
                progressTimer = nil
                
                let normalizedProgress = Double(serverProgress) / 100.0
                
                if stage.lowercased().contains("transcript") {
                    currentStage = .fetchingTranscript
                    stageProgress = min(normalizedProgress * 4.0, 1.0)
                } else if stage.lowercased().contains("analyz") {
                    currentStage = .analyzingContent
                    stageProgress = min((normalizedProgress - 0.25) * 4.0, 1.0)
                } else if stage.lowercased().contains("summary") || stage.lowercased().contains("generat") {
                    currentStage = .generatingSummary
                    stageProgress = min((normalizedProgress - 0.50) * 2.86, 1.0)
                } else if stage.lowercased().contains("notion") || stage.lowercased().contains("sav") {
                    currentStage = .savingToNotion
                    stageProgress = min((normalizedProgress - 0.85) * 6.67, 1.0)
                } else if stage.lowercased().contains("complete") {
                    currentStage = .savingToNotion
                    stageProgress = 1.0
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
    
    // MARK: - Progress Simulation
    
    private func startProgressSimulation() {
        currentStage = .fetchingTranscript
        stageProgress = 0.0
        advanceProgressWithinStage()
    }
    
    private func advanceProgressWithinStage() {
        let stage = currentStage
        let duration = stage.estimatedDuration
        let updateInterval = 0.1
        let progressIncrement = updateInterval / duration
        
        progressTimer = Timer.scheduledTimer(withTimeInterval: updateInterval, repeats: true) { timer in
            stageProgress += progressIncrement
            
            if stageProgress >= 1.0 {
                timer.invalidate()
                moveToNextStage()
            }
        }
    }
    
    private func moveToNextStage() {
        let stages = SummarizationStage.allCases
        guard let currentIndex = stages.firstIndex(of: currentStage),
              currentIndex + 1 < stages.count else {
            stallOnLastStage()
            return
        }
        
        stageProgress = 0.0
        currentStage = stages[currentIndex + 1]
        advanceProgressWithinStage()
    }
    
    private func stallOnLastStage() {
        progressTimer = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { timer in
            if stageProgress < 0.95 {
                stageProgress += 0.02
            }
        }
    }
}

// Corner radius helper
extension View {
    func cornerRadius(_ radius: CGFloat, corners: UIRectCorner) -> some View {
        clipShape(RoundedCorner(radius: radius, corners: corners))
    }
}

struct RoundedCorner: Shape {
    var radius: CGFloat = .infinity
    var corners: UIRectCorner = .allCorners
    
    func path(in rect: CGRect) -> Path {
        let path = UIBezierPath(
            roundedRect: rect,
            byRoundingCorners: corners,
            cornerRadii: CGSize(width: radius, height: radius)
        )
        return Path(path.cgPath)
    }
}

// MARK: - API Models

struct SummarizeResult: Codable {
    let success: Bool
    let title: String?
    let notionUrl: String?
    let error: String?
    let remaining: Int?
}
