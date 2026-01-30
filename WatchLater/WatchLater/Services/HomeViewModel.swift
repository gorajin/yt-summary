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
    
    /// Dedicated URLSession for YouTube requests with cookie storage
    /// YouTube requires session continuity between page load and caption fetch
    private lazy var youtubeSession: URLSession = {
        let config = URLSessionConfiguration.default
        config.httpCookieStorage = HTTPCookieStorage.shared
        config.httpCookieAcceptPolicy = .always
        config.httpShouldSetCookies = true
        // Add common headers that YouTube expects
        config.httpAdditionalHeaders = [
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
        ]
        return URLSession(configuration: config)
    }()
    
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
    /// Enhanced to try ALL available caption tracks, not just the first one
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
            pageRequest.setValue("en-US,en;q=0.9,ko;q=0.8", forHTTPHeaderField: "Accept-Language")
            pageRequest.setValue("text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", forHTTPHeaderField: "Accept")
            pageRequest.timeoutInterval = 20
            
            let (pageData, _) = try await youtubeSession.data(for: pageRequest)
            guard let pageHTML = String(data: pageData, encoding: .utf8) else {
                print("❌ Could not decode YouTube page")
                return nil
            }
            
            print("📝 Fetched YouTube page (\(pageHTML.count) bytes)")
            
            // Extract pot token first - YouTube 2025+ requires this or returns empty responses
            let potToken = extractPotToken(from: pageHTML)
            if let pot = potToken {
                print("📝 Found pot token (\(pot.count) chars)")
            } else {
                print("📝 ⚠️ No pot token found - captions may fail")
            }
            
            // Extract ALL caption tracks, not just the first one
            let captionTracks = extractAllCaptionTracks(from: pageHTML)
            print("📝 Found \(captionTracks.count) caption tracks")
            
            if captionTracks.isEmpty {
                print("❌ No caption tracks found in page")
                // Debug: Check if keywords exist
                if pageHTML.contains("captionTracks") {
                    print("📝 HTML contains 'captionTracks' but extraction failed")
                }
                return nil
            }
            
            // Sort tracks: prefer English, then auto-generated English, then Korean, then any
            let sortedTracks = captionTracks.sorted { a, b in
                let priority: (String) -> Int = { lang in
                    if lang.lowercased().hasPrefix("en") && !lang.contains("auto") { return 0 }
                    if lang.lowercased().hasPrefix("en") { return 1 }
                    if lang.lowercased().hasPrefix("ko") && !lang.contains("auto") { return 2 }
                    if lang.lowercased().hasPrefix("ko") { return 3 }
                    return 4
                }
                return priority(a.lang) < priority(b.lang)
            }
            
            for track in sortedTracks {
                print("📝 Trying caption track: \(track.lang)")
                
                // Strategy 1: Try the raw baseUrl first (YouTube might already include required params)
                if let rawURL = URL(string: track.baseUrl) {
                    print("📝 Trying raw caption URL...")
                    if let transcript = await fetchCaptionData(from: rawURL, format: "auto") {
                        print("✅ SUCCESS with raw URL from \(track.lang) (\(transcript.count) chars)")
                        return transcript
                    }
                }
                
                // Strategy 2: Try with different formats and pot token
                let formats = ["json3", "srv1", "srv3"]
                
                for format in formats {
                    var urlString = track.baseUrl
                    
                    // Handle format parameter
                    if urlString.contains("fmt=") {
                        // Replace existing format
                        urlString = urlString.replacingOccurrences(of: #"fmt=\w+"#, with: "fmt=\(format)", options: .regularExpression)
                    } else {
                        urlString += "&fmt=\(format)"
                    }
                    
                    // Add pot token if we have it and it's not already in URL
                    if let pot = potToken, !urlString.contains("&pot=") {
                        urlString += "&pot=\(pot)"
                    }
                    
                    guard let captionURL = URL(string: urlString) else { continue }
                    
                    // Try to fetch this caption track
                    if let transcript = await fetchCaptionData(from: captionURL, format: format) {
                        print("✅ Successfully got transcript from \(track.lang) with format \(format) (\(transcript.count) chars)")
                        return transcript
                    }
                }
            }
            
            print("❌ All caption tracks failed with URLSession approach")
            
            // Fallback: Try WebKit-based extraction with JavaScript execution
            // This executes YouTube's botguard to get the POT token dynamically
            print("📱 Trying WebKit-based extraction...")
            let webkitExtractor = WebKitTranscriptExtractor()
            if let transcript = await webkitExtractor.extractTranscript(videoId: id) {
                print("✅ WebKit extraction succeeded (\(transcript.count) chars)")
                return transcript
            }
            
            print("❌ All extraction methods failed, will use server fallback")
            return nil
            
        } catch {
            print("❌ Transcript fetch error: \(error.localizedDescription)")
            return nil
        }
    }
    
    /// Fetch caption data from a specific URL
    private func fetchCaptionData(from url: URL, format: String) async -> String? {
        var request = URLRequest(url: url)
        request.setValue(
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
            forHTTPHeaderField: "User-Agent"
        )
        request.setValue("https://www.youtube.com", forHTTPHeaderField: "Referer")
        request.setValue("https://www.youtube.com", forHTTPHeaderField: "Origin")
        request.setValue("en-US,en;q=0.9", forHTTPHeaderField: "Accept-Language")
        request.setValue("application/json, text/xml, */*", forHTTPHeaderField: "Accept")
        request.timeoutInterval = 15
        
        do {
            let (data, response) = try await youtubeSession.data(for: request)
            
            if let httpResponse = response as? HTTPURLResponse {
                print("📝 Caption response (\(format)): status=\(httpResponse.statusCode), size=\(data.count) bytes")
            }
            
            // If empty response, skip
            if data.count == 0 {
                return nil
            }
            
            // Try parsing based on format
            if format == "json3" {
                if let transcript = parseTranscriptJSON3(data) {
                    return transcript
                }
            }
            
            // Always try XML as fallback
            if let transcript = parseTranscriptXML(data) {
                return transcript
            }
            
            // Try JSON3 even if format was different (YouTube sometimes ignores fmt)
            if let transcript = parseTranscriptJSON3(data) {
                return transcript
            }
            
            return nil
        } catch {
            print("📝 Caption fetch error for \(format): \(error.localizedDescription)")
            return nil
        }
    }
    
    /// Extract ALL caption track URLs from YouTube page HTML
    /// Returns array of (language, baseUrl) tuples
    private func extractAllCaptionTracks(from html: String) -> [(lang: String, baseUrl: String)] {
        var tracks: [(lang: String, baseUrl: String)] = []
        
        // First, find the captionTracks section - use a more robust approach
        // Look for "captionTracks":[ and then find the matching ]
        guard let startIndex = html.range(of: "\"captionTracks\":[")?.upperBound else {
            print("📝 Could not find captionTracks in HTML")
            return []
        }
        
        // Find the matching closing bracket by counting brackets
        // Safety limit prevents infinite loop on malformed HTML
        var bracketCount = 1
        var endIndex = startIndex
        var searchIndex = startIndex
        var iterations = 0
        let maxIterations = 100000 // Caption tracks JSON is typically < 10KB
        
        while bracketCount > 0 && searchIndex < html.endIndex && iterations < maxIterations {
            iterations += 1
            let char = html[searchIndex]
            if char == "[" { bracketCount += 1 }
            else if char == "]" { bracketCount -= 1 }
            if bracketCount > 0 { searchIndex = html.index(after: searchIndex) }
            endIndex = searchIndex
        }
        
        if iterations >= maxIterations {
            print("📝 ⚠️ Caption extraction hit safety limit - malformed HTML?")
            return []
        }
        
        let captionTracksJSON = String(html[startIndex..<endIndex])
        print("📝 Extracted captionTracks JSON (\(captionTracksJSON.count) chars)")
        
        // Now extract individual caption tracks using patterns that handle nested objects
        // Look for baseUrl and languageCode pairs - use .*? which allows any chars including }
        let patterns = [
            // Pattern 1: baseUrl comes before languageCode
            #""baseUrl"\s*:\s*"([^"]+)".*?"languageCode"\s*:\s*"([^"]+)""#,
            // Pattern 2: languageCode comes before baseUrl  
            #""languageCode"\s*:\s*"([^"]+)".*?"baseUrl"\s*:\s*"([^"]+)""#
        ]
        
        for (patternIndex, pattern) in patterns.enumerated() {
            if let trackRegex = try? NSRegularExpression(pattern: pattern, options: .dotMatchesLineSeparators) {
                let matches = trackRegex.matches(in: captionTracksJSON, range: NSRange(captionTracksJSON.startIndex..., in: captionTracksJSON))
                
                for match in matches {
                    var urlString: String
                    var lang: String
                    
                    if patternIndex == 0 {
                        // baseUrl is group 1, languageCode is group 2
                        guard let urlRange = Range(match.range(at: 1), in: captionTracksJSON),
                              let langRange = Range(match.range(at: 2), in: captionTracksJSON) else { continue }
                        urlString = String(captionTracksJSON[urlRange])
                        lang = String(captionTracksJSON[langRange])
                    } else {
                        // languageCode is group 1, baseUrl is group 2
                        guard let langRange = Range(match.range(at: 1), in: captionTracksJSON),
                              let urlRange = Range(match.range(at: 2), in: captionTracksJSON) else { continue }
                        urlString = String(captionTracksJSON[urlRange])
                        lang = String(captionTracksJSON[langRange])
                    }
                    
                    // Unescape
                    urlString = urlString.replacingOccurrences(of: "\\u0026", with: "&")
                    urlString = urlString.replacingOccurrences(of: "\\/", with: "/")
                    
                    // Handle relative URLs
                    if urlString.hasPrefix("/") {
                        urlString = "https://www.youtube.com" + urlString
                    }
                    
                    // Avoid duplicates
                    if !tracks.contains(where: { $0.lang == lang }) {
                        tracks.append((lang: lang, baseUrl: urlString))
                    }
                }
                
                // If we found tracks, stop trying patterns
                if !tracks.isEmpty { break }
            }
        }
        
        // Log found tracks
        for track in tracks {
            print("📝 Found track: \(track.lang)")
        }
        
        return tracks
    }

    /// Extract captions URL from YouTube page HTML
    /// In 2025, YouTube requires a 'pot' (proof of origin token) parameter or returns empty responses
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
                
                // Try to extract 'pot' (proof of origin token) from the page if not already in URL
                // YouTube 2025 requires this or returns empty responses
                if !urlString.contains("&pot=") {
                    if let potToken = extractPotToken(from: html) {
                        urlString += "&pot=\(potToken)"
                        print("📝 Added pot token to caption URL")
                    }
                }
                
                if let url = URL(string: urlString) {
                    return url
                }
            }
        }
        
        return nil
    }
    
    /// Extract the 'pot' (proof of origin token) from YouTube page
    /// This token is required for timedtext API to return non-empty responses (2025+)
    /// YouTube 2026: Token is now in serviceIntegrityDimensions.poToken
    private func extractPotToken(from html: String) -> String? {
        // The pot token can appear in various locations in the page
        // Order matters - try the most common/reliable patterns first
        let patterns = [
            // 2026 format: serviceIntegrityDimensions contains poToken
            #""serviceIntegrityDimensions"\s*:\s*\{[^}]*"poToken"\s*:\s*"([^"]+)""#,
            // Alternative nesting formats
            #""poToken"\s*:\s*"([^"]+)""#,
            #""pot"\s*:\s*"([^"]+)""#,
            // URL parameter format
            #"pot=([^&\"]+)"#,
            // BotGuard token format (may be base64 encoded)
            #""botguardData"\s*:\s*\{[^}]*"token"\s*:\s*"([^"]+)""#
        ]
        
        for pattern in patterns {
            if let regex = try? NSRegularExpression(pattern: pattern, options: .dotMatchesLineSeparators),
               let match = regex.firstMatch(in: html, range: NSRange(html.startIndex..., in: html)),
               let range = Range(match.range(at: 1), in: html) {
                let token = String(html[range])
                // Skip very short tokens (likely false positives)
                if token.count > 20 {
                    print("📝 Found pot token (\(token.count) chars)")
                    return token
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
