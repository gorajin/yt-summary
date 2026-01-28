import Foundation
import SwiftUI

// MARK: - Summarization Stage Model

enum SummarizationStage: CaseIterable {
    case fetchingTranscript   // "Fetching transcript..."
    case analyzingContent     // "Analyzing content..."
    case generatingSummary    // "Generating summary..."
    case savingToNotion       // "Saving to Notion..."
    
    var displayText: String {
        switch self {
        case .fetchingTranscript: return "Fetching transcript..."
        case .analyzingContent: return "Analyzing content..."
        case .generatingSummary: return "Generating summary..."
        case .savingToNotion: return "Saving to Notion..."
        }
    }
    
    var icon: String {
        switch self {
        case .fetchingTranscript: return "text.bubble"
        case .analyzingContent: return "doc.text.magnifyingglass"
        case .generatingSummary: return "sparkles"
        case .savingToNotion: return "square.and.arrow.up"
        }
    }
    
    // Estimated duration in seconds for progress bar animation
    var estimatedDuration: Double {
        switch self {
        case .fetchingTranscript: return 3.0
        case .analyzingContent: return 5.0
        case .generatingSummary: return 25.0  // Longest step (Gemini processing)
        case .savingToNotion: return 4.0
        }
    }
}

@MainActor
class HomeViewModel: ObservableObject {
    @Published var isNotionConnected = false
    @Published var isProcessing = false
    @Published var statusMessage: String?
    @Published var isSuccess = false
    @Published var summariesRemaining: Int?
    
    // Progress tracking
    @Published var currentStage: SummarizationStage = .fetchingTranscript
    @Published var stageProgress: Double = 0.0  // 0.0 - 1.0 within current stage
    
    private let api = APIService.shared
    private var progressTimer: Timer?
    
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
        #if DEBUG
        // Debug: Test token with debug endpoint
        await debugToken(token: token)
        #endif
        
        do {
            let user = try await api.getProfile(authToken: token)
            isNotionConnected = user.notionConnected
            summariesRemaining = user.summariesRemaining
            print("Profile loaded: notionConnected=\(user.notionConnected)")
        } catch {
            print("Failed to load profile: \(error)")
        }
    }
    
    private func debugToken(token: String) async {
        let endpoint = URL(string: "https://watchlater.up.railway.app/debug/token")!
        var request = URLRequest(url: endpoint)
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        
        do {
            let (data, _) = try await URLSession.shared.data(for: request)
            if let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                print("🔍 DEBUG TOKEN RESULT: \(json)")
            }
        } catch {
            print("Debug token request failed: \(error)")
        }
    }
    
    // MARK: - Summarize with Client-Side Transcript Fetching
    
    func summarize(url: String, token: String) async {
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
            let response = try await api.summarize(url: url, transcript: transcript, authToken: token)
            
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
        }
        
        isProcessing = false
    }
    
    // MARK: - Client-Side Transcript Fetching
    
    /// Fetch transcript from YouTube (client-side to bypass IP blocking)
    private func fetchTranscript(for url: String) async -> String? {
        // Extract video ID - support various YouTube URL formats
        let patterns = [
            #"(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/shorts\/|youtube\.com\/live\/)([a-zA-Z0-9_-]{11})"#,
            #"(?:youtube\.com\/embed\/)([a-zA-Z0-9_-]{11})"#
        ]

        
        var videoId: String?
        for pattern in patterns {
            if let regex = try? NSRegularExpression(pattern: pattern),
               let match = regex.firstMatch(in: url, range: NSRange(url.startIndex..., in: url)),
               let range = Range(match.range(at: 1), in: url) {
                videoId = String(url[range])
                break
            }
        }
        
        guard let id = videoId else {
            print("❌ Could not extract video ID from: \(url)")
            return nil
        }
        
        print("📝 Extracted video ID: \(id)")
        
        // Try to get transcript using YouTube's page scraping
        do {
            // First, get the video page to find available captions
            let videoPageURL = URL(string: "https://www.youtube.com/watch?v=\(id)")!
            var pageRequest = URLRequest(url: videoPageURL)
            // Use a complete, realistic User-Agent to avoid bot detection
            pageRequest.setValue(
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
                forHTTPHeaderField: "User-Agent"
            )
            pageRequest.setValue("en-US,en;q=0.9", forHTTPHeaderField: "Accept-Language")
            pageRequest.timeoutInterval = 20
            
            let (pageData, _) = try await URLSession.shared.data(for: pageRequest)
            guard let pageHTML = String(data: pageData, encoding: .utf8) else {
                print("❌ Could not decode YouTube page")
                return nil
            }
            
            print("📝 Fetched YouTube page (\(pageHTML.count) bytes)")
            
            // Extract captions URL from ytInitialPlayerResponse
            if let captionsURL = extractCaptionsURL(from: pageHTML, videoId: id) {
                print("📝 Found captions URL: \(captionsURL)")
                
                var captionRequest = URLRequest(url: captionsURL)
                captionRequest.setValue(
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
                    forHTTPHeaderField: "User-Agent"
                )
                captionRequest.timeoutInterval = 15
                
                let (captionData, captionResponse) = try await URLSession.shared.data(for: captionRequest)
                
                // Log response details for debugging
                if let httpResponse = captionResponse as? HTTPURLResponse {
                    print("📝 Caption response status: \(httpResponse.statusCode)")
                }
                print("📝 Caption data size: \(captionData.count) bytes")
                
                // Try parsing as XML first, then JSON3 format
                if let transcript = parseTranscriptXML(captionData) {
                    print("✅ Successfully fetched transcript (\(transcript.count) chars)")
                    return transcript
                } else if let transcript = parseTranscriptJSON3(captionData) {
                    print("✅ Successfully fetched transcript from JSON3 (\(transcript.count) chars)")
                    return transcript
                } else {
                    // Log first 500 chars of response for debugging
                    if let responseStr = String(data: captionData, encoding: .utf8) {
                        print("❌ Failed to parse caption data. First 500 chars: \(String(responseStr.prefix(500)))")
                    }
                }
            } else {

                print("❌ No captions URL found in HTML")
                // Log a snippet for debugging
                if pageHTML.contains("captionTracks") {
                    print("📝 HTML contains 'captionTracks' but regex didn't match")
                }
                if pageHTML.contains("timedtext") {
                    print("📝 HTML contains 'timedtext' but regex didn't match")
                }
            }
            
            print("❌ No captions found for video")
            return nil
        } catch {
            print("❌ Transcript fetch error: \(error.localizedDescription)")
            return nil
        }
    }
    
    /// Extract captions URL from YouTube page HTML
    private func extractCaptionsURL(from html: String, videoId: String) -> URL? {
        // Look for timedtext URL in the page - multiple patterns for robustness
        let patterns = [
            #""baseUrl"\s*:\s*"(https://www\.youtube\.com/api/timedtext[^"]+)""#,
            #""captionTracks".*?"baseUrl"\s*:\s*"([^"]+)""#,
            #"timedtext[^"]*"[^}]*"baseUrl"\s*:\s*"([^"]+)""#
        ]
        
        for pattern in patterns {
            if let regex = try? NSRegularExpression(pattern: pattern, options: .dotMatchesLineSeparators),
               let match = regex.firstMatch(in: html, range: NSRange(html.startIndex..., in: html)),
               let range = Range(match.range(at: 1), in: html) {
                var urlString = String(html[range])
                // Unescape unicode and special characters
                urlString = urlString.replacingOccurrences(of: "\\u0026", with: "&")
                urlString = urlString.replacingOccurrences(of: "\\/", with: "/")
                
                // Handle relative URLs - prepend YouTube base URL if needed
                if urlString.hasPrefix("/") {
                    urlString = "https://www.youtube.com" + urlString
                }
                
                // Add fmt=json3 for more reliable responses (YouTube returns empty for some requests)
                if !urlString.contains("fmt=") {
                    urlString += "&fmt=json3"
                }
                
                if let url = URL(string: urlString) {
                    return url
                }
            }
        }
        
        return nil
    }

    
    /// Parse transcript from YouTube's XML format
    private func parseTranscriptXML(_ data: Data) -> String? {
        guard let xmlString = String(data: data, encoding: .utf8) else { return nil }
        
        // Simple XML parsing - extract text between <text> tags
        var transcript = ""
        let pattern = #"<text[^>]*>([^<]*)</text>"#
        
        if let regex = try? NSRegularExpression(pattern: pattern) {
            let matches = regex.matches(in: xmlString, range: NSRange(xmlString.startIndex..., in: xmlString))
            
            for match in matches {
                if let range = Range(match.range(at: 1), in: xmlString) {
                    var text = String(xmlString[range])
                    // Decode HTML entities
                    text = text.replacingOccurrences(of: "&amp;", with: "&")
                    text = text.replacingOccurrences(of: "&lt;", with: "<")
                    text = text.replacingOccurrences(of: "&gt;", with: ">")
                    text = text.replacingOccurrences(of: "&quot;", with: "\"")
                    text = text.replacingOccurrences(of: "&#39;", with: "'")
                    text = text.replacingOccurrences(of: "\n", with: " ")
                    transcript += text + " "
                }
            }
        }
        
        return transcript.isEmpty ? nil : transcript.trimmingCharacters(in: .whitespaces)
    }
    
    /// Parse transcript from YouTube's JSON3 format (alternative to XML)
    private func parseTranscriptJSON3(_ data: Data) -> String? {
        // JSON3 format: {"events":[{"segs":[{"utf8":"text"}]},...]}
        guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let events = json["events"] as? [[String: Any]] else {
            return nil
        }
        
        var transcript = ""
        for event in events {
            if let segs = event["segs"] as? [[String: Any]] {
                for seg in segs {
                    if let text = seg["utf8"] as? String {
                        transcript += text
                    }
                }
            }
        }
        
        return transcript.isEmpty ? nil : transcript.trimmingCharacters(in: .whitespaces)
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
