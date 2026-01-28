import UIKit
import SwiftUI

class ShareViewController: UIViewController {
    
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
        // Show loading - update UI through the hosted SwiftUI view
        
        Task {
            do {
                // Fetch transcript client-side (bypasses YouTube IP blocking)
                let transcript = await fetchTranscript(for: url)
                let result = try await callSummarizeAPI(url: url, token: token, transcript: transcript)
                
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
            print("📱 Share: Could not extract video ID")
            return nil
        }
        
        print("📱 Share: Extracted video ID: \(id)")
        
        // Try to get transcript using YouTube's page scraping
        do {
            // First, get the video page to find available captions
            let videoPageURL = URL(string: "https://www.youtube.com/watch?v=\(id)")!
            var pageRequest = URLRequest(url: videoPageURL)
            pageRequest.setValue(
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
                forHTTPHeaderField: "User-Agent"
            )
            pageRequest.setValue("en-US,en;q=0.9,ko;q=0.8", forHTTPHeaderField: "Accept-Language")
            pageRequest.setValue("text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", forHTTPHeaderField: "Accept")
            pageRequest.timeoutInterval = 20
            
            let (pageData, _) = try await URLSession.shared.data(for: pageRequest)
            guard let pageHTML = String(data: pageData, encoding: .utf8) else {
                print("📱 Share: Could not decode YouTube page")
                return nil
            }
            
            print("📱 Share: Fetched YouTube page (\(pageHTML.count) bytes)")
            
            // Extract ALL caption tracks, not just the first one
            let captionTracks = extractAllCaptionTracks(from: pageHTML)
            print("📱 Share: Found \(captionTracks.count) caption tracks")
            
            if captionTracks.isEmpty {
                print("📱 Share: ❌ No caption tracks found in page")
                if pageHTML.contains("captionTracks") {
                    print("📱 Share: HTML contains 'captionTracks' but extraction failed")
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
                print("📱 Share: Trying caption track: \(track.lang)")
                
                // Try with different formats
                let formats = ["json3", "srv1", "srv3"]
                
                for format in formats {
                    var urlString = track.baseUrl
                    
                    // Handle format parameter
                    if urlString.contains("fmt=") {
                        urlString = urlString.replacingOccurrences(of: #"fmt=\w+"#, with: "fmt=\(format)", options: .regularExpression)
                    } else {
                        urlString += "&fmt=\(format)"
                    }
                    
                    guard let captionURL = URL(string: urlString) else { continue }
                    
                    // Try to fetch this caption track
                    if let transcript = await fetchCaptionData(from: captionURL, format: format) {
                        print("📱 Share: ✅ Got transcript from \(track.lang) with format \(format) (\(transcript.count) chars)")
                        return transcript
                    }
                }
            }
            
            print("📱 Share: ❌ All caption tracks failed")
            return nil
            
        } catch {
            print("📱 Share: Transcript fetch error: \(error.localizedDescription)")
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
            let (data, response) = try await URLSession.shared.data(for: request)
            
            if let httpResponse = response as? HTTPURLResponse {
                print("📱 Share: Caption response (\(format)): status=\(httpResponse.statusCode), size=\(data.count) bytes")
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
            
            // Try JSON3 even if format was different
            if let transcript = parseTranscriptJSON3(data) {
                return transcript
            }
            
            return nil
        } catch {
            print("📱 Share: Caption fetch error for \(format): \(error.localizedDescription)")
            return nil
        }
    }
    
    /// Extract ALL caption track URLs from YouTube page HTML
    private func extractAllCaptionTracks(from html: String) -> [(lang: String, baseUrl: String)] {
        var tracks: [(lang: String, baseUrl: String)] = []
        
        // Look for captionTracks array in ytInitialPlayerResponse
        let pattern = #""captionTracks"\s*:\s*\[(.*?)\]"#
        
        guard let regex = try? NSRegularExpression(pattern: pattern, options: .dotMatchesLineSeparators),
              let match = regex.firstMatch(in: html, range: NSRange(html.startIndex..., in: html)),
              let range = Range(match.range(at: 1), in: html) else {
            print("📱 Share: Could not find captionTracks array in HTML")
            return []
        }
        
        let captionTracksJSON = String(html[range])
        
        // Extract individual tracks - try multiple patterns for robustness
        let trackPattern = #"\{"baseUrl"\s*:\s*"([^"]+)"[^}]*"languageCode"\s*:\s*"([^"]+)""#
        let altTrackPattern = #""languageCode"\s*:\s*"([^"]+)"[^}]*"baseUrl"\s*:\s*"([^"]+)""#
        
        // Try first pattern
        if let trackRegex = try? NSRegularExpression(pattern: trackPattern, options: .dotMatchesLineSeparators) {
            let matches = trackRegex.matches(in: captionTracksJSON, range: NSRange(captionTracksJSON.startIndex..., in: captionTracksJSON))
            
            for match in matches {
                if let urlRange = Range(match.range(at: 1), in: captionTracksJSON),
                   let langRange = Range(match.range(at: 2), in: captionTracksJSON) {
                    var urlString = String(captionTracksJSON[urlRange])
                    let lang = String(captionTracksJSON[langRange])
                    
                    // Unescape
                    urlString = urlString.replacingOccurrences(of: "\\u0026", with: "&")
                    urlString = urlString.replacingOccurrences(of: "\\/", with: "/")
                    
                    if urlString.hasPrefix("/") {
                        urlString = "https://www.youtube.com" + urlString
                    }
                    
                    tracks.append((lang: lang, baseUrl: urlString))
                }
            }
        }
        
        // If no matches, try alternate pattern
        if tracks.isEmpty {
            if let trackRegex = try? NSRegularExpression(pattern: altTrackPattern, options: .dotMatchesLineSeparators) {
                let matches = trackRegex.matches(in: captionTracksJSON, range: NSRange(captionTracksJSON.startIndex..., in: captionTracksJSON))
                
                for match in matches {
                    if let langRange = Range(match.range(at: 1), in: captionTracksJSON),
                       let urlRange = Range(match.range(at: 2), in: captionTracksJSON) {
                        var urlString = String(captionTracksJSON[urlRange])
                        let lang = String(captionTracksJSON[langRange])
                        
                        urlString = urlString.replacingOccurrences(of: "\\u0026", with: "&")
                        urlString = urlString.replacingOccurrences(of: "\\/", with: "/")
                        
                        if urlString.hasPrefix("/") {
                            urlString = "https://www.youtube.com" + urlString
                        }
                        
                        tracks.append((lang: lang, baseUrl: urlString))
                    }
                }
            }
        }
        
        // Log found tracks
        for track in tracks {
            print("📱 Share: Found track: \(track.lang)")
        }
        
        return tracks
    }

    /// Extract captions URL from YouTube page HTML
    /// In 2025, YouTube requires a 'pot' (proof of origin token) parameter or returns empty responses
    private func extractCaptionsURL(from html: String, videoId: String) -> URL? {
        // Look for timedtext URL in the page
        let patterns = [
            #""baseUrl"\s*:\s*"(https://www\.youtube\.com/api/timedtext[^"]+)""#,
            #""captionTracks".*?"baseUrl"\s*:\s*"([^"]+)""#
        ]
        
        for pattern in patterns {
            if let regex = try? NSRegularExpression(pattern: pattern, options: .dotMatchesLineSeparators),
               let match = regex.firstMatch(in: html, range: NSRange(html.startIndex..., in: html)),
               let range = Range(match.range(at: 1), in: html) {
                var urlString = String(html[range])
                // Unescape unicode
                urlString = urlString.replacingOccurrences(of: "\\u0026", with: "&")
                urlString = urlString.replacingOccurrences(of: "\\/", with: "/")
                
                // Handle relative URLs - prepend YouTube base URL if needed
                if urlString.hasPrefix("/") {
                    urlString = "https://www.youtube.com" + urlString
                }
                
                // Add fmt=json3 for more reliable JSON responses (YouTube returns empty for some XML requests)
                if !urlString.contains("fmt=") {
                    urlString += "&fmt=json3"
                }
                
                // Try to extract 'pot' (proof of origin token) from the page if not already in URL
                // YouTube 2025 requires this or returns empty responses
                if !urlString.contains("&pot=") {
                    if let potToken = extractPotToken(from: html) {
                        urlString += "&pot=\(potToken)"
                        print("📱 Share: Added pot token to caption URL")
                    }
                }
                
                print("📱 Share: Caption URL built: \(urlString.prefix(100))...")
                
                if let url = URL(string: urlString) {
                    return url
                }
            }
        }
        
        return nil
    }
    
    /// Extract the 'pot' (proof of origin token) from YouTube page
    /// This token is required for timedtext API to return non-empty responses (2025+)
    private func extractPotToken(from html: String) -> String? {
        // The pot token can appear in various locations in the page
        let patterns = [
            #""pot"\s*:\s*"([^"]+)""#,
            #""poToken"\s*:\s*"([^"]+)""#,
            #"pot=([^&\"]+)"#
        ]
        
        for pattern in patterns {
            if let regex = try? NSRegularExpression(pattern: pattern),
               let match = regex.firstMatch(in: html, range: NSRange(html.startIndex..., in: html)),
               let range = Range(match.range(at: 1), in: html) {
                let token = String(html[range])
                print("📱 Share: Found pot token (\(token.count) chars)")
                return token
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
        // JSON3 format: {"events":[{"segs":[{"utf8":"text"}],...]}
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
    
    private func callSummarizeAPI(url: String, token: String, transcript: String?) async throws -> SummarizeResult {
        let endpoint = URL(string: "https://watchlater.up.railway.app/summarize")!
        
        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.timeoutInterval = 120
        
        // Include transcript if available (bypasses server-side YouTube fetch)
        var bodyDict: [String: String] = ["url": url]
        if let transcript = transcript {
            bodyDict["transcript"] = transcript
        }
        request.httpBody = try JSONSerialization.data(withJSONObject: bodyDict)
        
        let (data, response) = try await URLSession.shared.data(for: request)
        
        // Debug: log the raw response
        if let responseString = String(data: data, encoding: .utf8) {
            print("API Response: \(responseString.prefix(500))")
        }
        
        // Check HTTP status
        guard let httpResponse = response as? HTTPURLResponse else {
            throw NSError(domain: "WatchLater", code: 0,
                userInfo: [NSLocalizedDescriptionKey: "Invalid server response"])
        }
        
        print("HTTP Status: \(httpResponse.statusCode)")
        
        // Handle specific error codes
        if httpResponse.statusCode == 401 {
            throw NSError(domain: "WatchLater", code: 401, 
                userInfo: [NSLocalizedDescriptionKey: "Please sign in to the WatchLater app first"])
        }
        
        if httpResponse.statusCode == 429 {
            throw NSError(domain: "WatchLater", code: 429,
                userInfo: [NSLocalizedDescriptionKey: "Rate limit exceeded. Please wait a moment."])
        }
        
        // Handle all other HTTP errors (400, 500, etc.) BEFORE trying to decode
        if httpResponse.statusCode >= 400 {
            // Backend returns {"detail": "error message"} for HTTP errors
            if let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let detail = json["detail"] as? String {
                throw NSError(domain: "WatchLater", code: httpResponse.statusCode,
                    userInfo: [NSLocalizedDescriptionKey: detail])
            }
            throw NSError(domain: "WatchLater", code: httpResponse.statusCode,
                userInfo: [NSLocalizedDescriptionKey: "Server error (\(httpResponse.statusCode))"])
        }
        
        // Only decode SummarizeResult for successful responses
        do {
            return try JSONDecoder().decode(SummarizeResult.self, from: data)
        } catch {
            print("JSON Decode Error: \(error)")
            // Fallback: try to extract any error message
            if let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                if let detail = json["detail"] as? String {
                    throw NSError(domain: "WatchLater", code: 0, 
                        userInfo: [NSLocalizedDescriptionKey: detail])
                }
                if let errorMsg = json["error"] as? String {
                    throw NSError(domain: "WatchLater", code: 0,
                        userInfo: [NSLocalizedDescriptionKey: errorMsg])
                }
            }
            throw NSError(domain: "WatchLater", code: 0,
                userInfo: [NSLocalizedDescriptionKey: "Failed to read server response"])
        }
    }
    
    private func showSuccess(title: String) {
        // Stop progress timer
        NotificationCenter.default.post(name: NSNotification.Name("StopProgressTimer"), object: nil)
        
        let alert = UIAlertController(title: "✅ Saved!", message: title, preferredStyle: .alert)
        alert.addAction(UIAlertAction(title: "Done", style: .default) { [weak self] _ in
            self?.extensionContext?.completeRequest(returningItems: nil, completionHandler: nil)
        })
        present(alert, animated: true)
    }
    
    private func showError(_ message: String) {
        // Stop progress timer
        NotificationCenter.default.post(name: NSNotification.Name("StopProgressTimer"), object: nil)
        
        let alert = UIAlertController(title: "Error", message: message, preferredStyle: .alert)
        alert.addAction(UIAlertAction(title: "OK", style: .cancel) { [weak self] _ in
            self?.extensionContext?.cancelRequest(withError: NSError(domain: "WatchLater", code: 1))
        })
        present(alert, animated: true)
    }
}


// MARK: - Progress Stage Model

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

// MARK: - SwiftUI Share View

struct ShareExtensionView: View {
    let url: String
    let onSave: () -> Void
    let onCancel: () -> Void
    
    @State private var isLoading = false
    @State private var currentStage: SummarizationStage = .fetchingTranscript
    @State private var stageProgress: Double = 0.0  // 0.0 - 1.0 within current stage
    @State private var progressTimer: Timer? = nil
    
    /// Computed property for overall progress (0.0 - 1.0)
    private var overallProgress: Double {
        let stages = SummarizationStage.allCases
        guard let currentIndex = stages.firstIndex(of: currentStage) else { return 0 }
        
        let completedStages = Double(currentIndex)
        let totalStages = Double(stages.count)
        
        // Each stage contributes equally + current stage's partial progress
        return (completedStages + stageProgress) / totalStages
    }
    
    /// Extract video ID from YouTube URL
    private var videoId: String? {
        let patterns = [
            #"(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/shorts\/)([a-zA-Z0-9_-]{11})"#,
            #"(?:youtube\.com\/embed\/)([a-zA-Z0-9_-]{11})"#
        ]
        
        for pattern in patterns {
            if let regex = try? NSRegularExpression(pattern: pattern),
               let match = regex.firstMatch(in: url, range: NSRange(url.startIndex..., in: url)),
               let range = Range(match.range(at: 1), in: url) {
                return String(url[range])
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
                    // Thumbnail
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
                    // Haptic feedback
                    let impactFeedback = UIImpactFeedbackGenerator(style: .medium)
                    impactFeedback.impactOccurred()
                    
                    isLoading = true
                    startProgressSimulation()
                    onSave()
                }) {
                    if isLoading {
                        // Enhanced progress UI
                        VStack(spacing: 10) {
                            // Stage indicator with icon
                            HStack(spacing: 8) {
                                Image(systemName: currentStage.icon)
                                    .font(.subheadline)
                                Text(currentStage.displayText)
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
        let updateInterval = 0.1  // Update every 100ms
        let progressIncrement = updateInterval / duration
        
        progressTimer = Timer.scheduledTimer(withTimeInterval: updateInterval, repeats: true) { timer in
            stageProgress += progressIncrement
            
            // Move to next stage when current completes
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
        progressTimer = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { timer in
            if stageProgress < 0.95 {
                stageProgress += 0.02  // Very slow progress
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
    let remaining: Int?  // Summaries remaining this month
}
