import Foundation
import SwiftUI
import os.log

private let homeLog = OSLog(subsystem: "com.watchlater.app", category: "HomeViewModel")

// SummarizationStage is defined in the shared SummarizationStage.swift file

@MainActor
class HomeViewModel: ObservableObject {
    @Published var isNotionConnected = false
    @Published var isProcessing = false
    @Published var isLoadingProfile = true  // Show skeleton initially
    @Published var statusMessage: String?
    @Published var isSuccess = false
    @Published var summariesRemaining: Int?
    @Published var quotaExceeded = false  // Triggers paywall

    // Progress tracking
    @Published var currentStage: SummarizationStage = .fetchingTranscript
    @Published var stageProgress: Double = 0.0  // 0.0 - 1.0 within current stage

    // Export content (for non-Notion save targets)
    @Published var lastExportContent: ExportContent?

    struct ExportContent {
        let text: String
        let filename: String
        let title: String
    }
    
    private let api = APIService.shared
    private var progressTimer: Timer?
    private let transcriptExtractor = TranscriptExtractor(logPrefix: "📝")
    
    /// Computed property for overall progress (0.0 - 1.0)
    var overallProgress: Double {
        let stages = SummarizationStage.allCases
        guard let currentIndex = stages.firstIndex(of: currentStage) else { return 0 }
        
        let completedStages = Double(currentIndex)
        let totalStages = Double(stages.count)
        
        // Each stage contributes equally + current stage's partial progress
        return (completedStages + stageProgress) / totalStages
    }
    
    // MARK: - Load Profile
    
    func loadProfile(token: String) async {
        isLoadingProfile = true
        do {
            async let userTask = api.getProfile(authToken: token)
            async let configTask = api.getExtractionConfig(authToken: token)
            
            // Wait for both concurrent requests
            let (user, config) = try await (userTask, configTask)
            
            // Apply profile
            isNotionConnected = user.notionConnected
            summariesRemaining = user.summariesRemaining
            
            // Apply and persist config
            config.save()
            os_log("Profile loaded: notionConnected=%{public}@", log: homeLog, type: .info, "\(user.notionConnected)")
            os_log("Extraction config loaded: v%d with %d patterns", log: homeLog, type: .info, config.version, config.captionTrackPatterns.count)
            
        } catch {
            os_log("Failed to load profile or config: %{public}@", log: homeLog, type: .error, "\(error)")
        }
        isLoadingProfile = false
    }
    
    // MARK: - Summarize with Client-Side Transcript Fetching
    
    func summarize(url: String, token: String, summaryFormat: String = "detailed", language: String = "en", saveTarget: SaveTarget = .notion) async {
        isProcessing = true
        statusMessage = nil
        isSuccess = false
        lastExportContent = nil
        currentStage = .fetchingTranscript
        stageProgress = 0.0

        // Start progress simulation
        startProgressSimulation()

        do {
            // Fetch transcript client-side to bypass YouTube IP blocking
            os_log("Starting client-side transcript fetch...", log: homeLog, type: .info)
            let transcript = await fetchTranscript(for: url)

            if let transcript = transcript {
                os_log("Got client transcript (%d chars)", log: homeLog, type: .info, transcript.count)
            } else {
                os_log("Client-side transcript fetch failed, falling back to server", log: homeLog, type: .error)
            }

            // Call API with transcript (or without as fallback)
            let response = try await api.summarize(url: url, transcript: transcript, authToken: token, summaryFormat: summaryFormat, language: language)

            // Stop progress timer
            stopProgressTimer()

            if response.success {
                summariesRemaining = response.remaining

                // For non-Notion targets, fetch the export
                if saveTarget != .notion {
                    os_log("Fetching export for target: %{public}@", log: homeLog, type: .info, saveTarget.rawValue)
                    let exportFormat = saveTarget == .appleNotes ? "html" : "markdown"
                    if let summaryId = response.summaryId {
                        let export = try await api.exportSummary(
                            summaryId: summaryId,
                            format: exportFormat,
                            authToken: token
                        )
                        lastExportContent = ExportContent(
                            text: export.content,
                            filename: export.filename,
                            title: response.title ?? "Summary"
                        )
                        statusMessage = "✅ Ready to save: \(response.title ?? "Summary")"
                    } else {
                        statusMessage = "✅ Saved: \(response.title ?? "Summary")"
                    }
                } else {
                    statusMessage = "✅ Saved: \(response.title ?? "Summary")"
                }
                isSuccess = true
            } else {
                statusMessage = response.error ?? "Unknown error"
                isSuccess = false
            }
        } catch {
            stopProgressTimer()
            statusMessage = error.localizedDescription
            isSuccess = false

            // Detect quota limit (429) and trigger paywall
            if let apiError = error as? APIError, case .rateLimited = apiError {
                quotaExceeded = true
            }
        }

        isProcessing = false
    }
    
    /// Fetch transcript from YouTube using shared TranscriptExtractor
    /// Falls back to WebKit extraction if URLSession-based approach fails
    private func fetchTranscript(for url: String) async -> String? {
        // Try shared extractor first (URLSession-based)
        if let transcript = await transcriptExtractor.fetchTranscript(for: url) {
            return transcript
        }
        
        // Fallback: WebKit-based extraction with JavaScript execution
        guard let videoId = transcriptExtractor.extractVideoId(from: url) else { return nil }
        
        os_log("Trying WebKit-based extraction...", log: homeLog, type: .info)
        let webkitExtractor = WebKitTranscriptExtractor()
        if let transcript = await webkitExtractor.extractTranscript(videoId: videoId) {
            os_log("WebKit extraction succeeded (%d chars)", log: homeLog, type: .info, transcript.count)
            return transcript
        }
        
        os_log("All extraction methods failed, will use server fallback", log: homeLog, type: .error)
        return nil
    }
    
    // MARK: - Progress Simulation

    
    private func startProgressSimulation() {
        stopProgressTimer()  // Invalidate any existing timer to prevent leaks
        currentStage = .fetchingTranscript
        stageProgress = 0.0
        advanceProgressWithinStage()
    }
    
    private func advanceProgressWithinStage() {
        let stage = currentStage
        let duration = stage.estimatedDuration
        let updateInterval = 0.1  // Update every 100ms
        let progressIncrement = updateInterval / duration
        
        progressTimer = Timer.scheduledTimer(withTimeInterval: updateInterval, repeats: true) { [weak self] timer in
            guard let self = self else {
                timer.invalidate()
                return
            }
            
            Task { @MainActor in
                self.stageProgress += progressIncrement
                
                // Move to next stage when current completes
                if self.stageProgress >= 1.0 {
                    timer.invalidate()
                    self.moveToNextStage()
                }
            }
        }
    }
    
    private func moveToNextStage() {
        let stages = SummarizationStage.allCases
        guard let currentIndex = stages.firstIndex(of: currentStage),
              currentIndex + 1 < stages.count else {
            // On last stage, slow down progress (wait for actual completion)
            stallOnLastStage()
            return
        }
        
        stageProgress = 0.0
        currentStage = stages[currentIndex + 1]
        advanceProgressWithinStage()
    }
    
    private func stallOnLastStage() {
        // Slow progress on last stage - API will complete and dismiss
        stopProgressTimer()  // Invalidate previous timer before creating new one
        progressTimer = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { [weak self] timer in
            guard let self = self else {
                timer.invalidate()
                return
            }
            Task { @MainActor in
                if self.stageProgress < 0.95 {
                    self.stageProgress += 0.02  // Very slow progress
                }
            }
        }
    }
    
    private func stopProgressTimer() {
        progressTimer?.invalidate()
        progressTimer = nil
    }
    
    // MARK: - Notion OAuth
    
    func startNotionOAuth(userId: String) async {
        do {
            let authURL = try await api.getNotionAuthURL(userId: userId)
            await MainActor.run {
                UIApplication.shared.open(authURL)
            }
        } catch {
            statusMessage = "Failed to start Notion connection: \(error.localizedDescription)"
            isSuccess = false
        }
    }
}
