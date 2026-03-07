import Foundation
import SwiftUI

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
            print("Profile loaded: notionConnected=\(user.notionConnected)")
            print("Extraction config loaded: v\(config.version) with \(config.captionTrackPatterns.count) patterns")
            
        } catch {
            print("Failed to load profile or config: \(error)")
        }
        isLoadingProfile = false
    }
    
    // MARK: - Summarize with Client-Side Transcript Fetching
    
    func summarize(url: String, token: String, summaryFormat: String = "detailed", language: String = "en") async {
        isProcessing = true
        statusMessage = nil
        isSuccess = false
        currentStage = .fetchingTranscript
        stageProgress = 0.0
        
        // Start progress simulation
        startProgressSimulation()
        
        do {
            // Phase 7: Fetch transcript client-side to bypass YouTube IP blocking
            print("📝 Starting client-side transcript fetch...")
            let transcript = await fetchTranscript(for: url)
            
            if let transcript = transcript {
                print("📝 Got client transcript (\(transcript.count) chars)")
            } else {
                print("⚠️ Client-side transcript fetch failed, falling back to server")
            }
            
            // Call API with transcript (or without as fallback)
            let response = try await api.summarize(url: url, transcript: transcript, authToken: token, summaryFormat: summaryFormat, language: language)
            
            // Stop progress timer
            stopProgressTimer()
            
            if response.success {
                statusMessage = "✅ Saved: \(response.title ?? "Summary")"
                isSuccess = true
                summariesRemaining = response.remaining
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
        
        print("📱 Trying WebKit-based extraction...")
        let webkitExtractor = WebKitTranscriptExtractor()
        if let transcript = await webkitExtractor.extractTranscript(videoId: videoId) {
            print("✅ WebKit extraction succeeded (\(transcript.count) chars)")
            return transcript
        }
        
        print("❌ All extraction methods failed, will use server fallback")
        return nil
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
        progressTimer = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { [weak self] _ in
            guard let self = self else { return }
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
