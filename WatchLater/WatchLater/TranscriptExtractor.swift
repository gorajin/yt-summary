//
//  TranscriptExtractor.swift
//  WatchLater
//
//  Shared transcript extraction logic used by both the main app and Share Extension.
//  This file should be added to both targets in Xcode.
//

import Foundation

/// Shared transcript extractor for YouTube videos.
/// Handles client-side caption fetching with multiple strategies for robustness.
class TranscriptExtractor {
    
    // MARK: - Types
    
    struct CaptionTrack {
        let lang: String
        let baseUrl: String
    }
    
    // MARK: - Properties
    
    /// Dedicated URLSession with cookie storage for YouTube session continuity
    private lazy var youtubeSession: URLSession = {
        let config = URLSessionConfiguration.default
        config.httpCookieStorage = HTTPCookieStorage.shared
        config.httpCookieAcceptPolicy = .always
        config.httpShouldSetCookies = true
        config.httpAdditionalHeaders = [
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
        ]
        return URLSession(configuration: config)
    }()
    
    private let logPrefix: String
    
    // MARK: - Init
    
    /// - Parameter logPrefix: Prefix for log messages (e.g. "📝" for main app, "📱 Share:" for extension)
    init(logPrefix: String = "📝") {
        self.logPrefix = logPrefix
    }
    
    // MARK: - Public API
    
    /// Extract video ID from a YouTube URL
    func extractVideoId(from url: String) -> String? {
        let patterns = [
            #"(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/shorts\/|youtube\.com\/live\/)([a-zA-Z0-9_-]{11})"#,
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
    
    /// Static convenience for one-off calls (e.g. HomeView thumbnail)
    static func extractVideoId(from url: String) -> String? {
        TranscriptExtractor().extractVideoId(from: url)
    }
    
    /// Fetch transcript from YouTube (client-side to bypass IP blocking)
    /// Tries ALL available caption tracks with multiple format strategies
    func fetchTranscript(for url: String) async -> String? {
        guard let videoId = extractVideoId(from: url) else {
            log("Could not extract video ID from: \(url)")
            return nil
        }
        
        log("Extracted video ID: \(videoId)")
        
        do {
            // Step 1: Fetch YouTube page HTML
            let videoPageURL = URL(string: "https://www.youtube.com/watch?v=\(videoId)")!
            var pageRequest = URLRequest(url: videoPageURL)
            pageRequest.setValue(
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
                forHTTPHeaderField: "User-Agent"
            )
            pageRequest.setValue("en-US,en;q=0.9,ko;q=0.8", forHTTPHeaderField: "Accept-Language")
            pageRequest.setValue("text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", forHTTPHeaderField: "Accept")
            pageRequest.timeoutInterval = 20
            
            let (pageData, _) = try await youtubeSession.data(for: pageRequest)
            guard let pageHTML = String(data: pageData, encoding: .utf8) else {
                log("Could not decode YouTube page")
                return nil
            }
            
            log("Fetched YouTube page (\(pageHTML.count) bytes)")
            
            // Step 2: Extract proof-of-origin token (required 2025+)
            let potToken = extractPotToken(from: pageHTML)
            if let pot = potToken {
                log("Found pot token (\(pot.count) chars)")
            } else {
                log("⚠️ No pot token found - captions may fail")
            }
            
            // Step 3: Extract ALL caption tracks
            let captionTracks = extractAllCaptionTracks(from: pageHTML)
            log("Found \(captionTracks.count) caption tracks")
            
            if captionTracks.isEmpty {
                log("❌ No caption tracks found in page")
                if pageHTML.contains("captionTracks") {
                    log("HTML contains 'captionTracks' but extraction failed")
                }
                return nil
            }
            
            // Step 4: Sort tracks by language preference
            let sortedTracks = sortTracksByPreference(captionTracks)
            
            // Step 5: Try each track with multiple formats
            for track in sortedTracks {
                log("Trying caption track: \(track.lang)")
                
                // Strategy 1: Raw URL
                if let rawURL = URL(string: track.baseUrl) {
                    if let transcript = await fetchCaptionData(from: rawURL, format: "auto") {
                        log("✅ SUCCESS with raw URL from \(track.lang) (\(transcript.count) chars)")
                        return transcript
                    }
                }
                
                // Strategy 2: Different formats + pot token
                let formats = ["json3", "srv1", "srv3"]
                for format in formats {
                    var urlString = track.baseUrl
                    
                    if urlString.contains("fmt=") {
                        urlString = urlString.replacingOccurrences(of: #"fmt=\w+"#, with: "fmt=\(format)", options: .regularExpression)
                    } else {
                        urlString += "&fmt=\(format)"
                    }
                    
                    if let pot = potToken, !urlString.contains("&pot=") {
                        urlString += "&pot=\(pot)"
                    }
                    
                    guard let captionURL = URL(string: urlString) else { continue }
                    
                    if let transcript = await fetchCaptionData(from: captionURL, format: format) {
                        log("✅ Got transcript from \(track.lang) with format \(format) (\(transcript.count) chars)")
                        return transcript
                    }
                }
            }
            
            log("❌ All caption tracks failed")
            return nil
            
        } catch {
            log("Transcript fetch error: \(error.localizedDescription)")
            return nil
        }
    }
    
    // MARK: - Caption Data Fetching
    
    func fetchCaptionData(from url: URL, format: String) async -> String? {
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
                log("Caption response (\(format)): status=\(httpResponse.statusCode), size=\(data.count) bytes")
            }
            
            if data.count == 0 { return nil }
            
            // Try parsing based on format
            if format == "json3", let transcript = parseTranscriptJSON3(data) {
                return transcript
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
            log("Caption fetch error for \(format): \(error.localizedDescription)")
            return nil
        }
    }
    
    // MARK: - HTML Parsing
    
    /// Extract ALL caption track URLs from YouTube page HTML
    func extractAllCaptionTracks(from html: String) -> [CaptionTrack] {
        var tracks: [CaptionTrack] = []
        
        guard let startIndex = html.range(of: "\"captionTracks\":[")?.upperBound else {
            log("Could not find captionTracks in HTML")
            return []
        }
        
        // Find the matching closing bracket
        var bracketCount = 1
        var endIndex = startIndex
        var searchIndex = startIndex
        var iterations = 0
        let maxIterations = 100000
        
        while bracketCount > 0 && searchIndex < html.endIndex && iterations < maxIterations {
            iterations += 1
            let char = html[searchIndex]
            if char == "[" { bracketCount += 1 }
            else if char == "]" { bracketCount -= 1 }
            if bracketCount > 0 { searchIndex = html.index(after: searchIndex) }
            endIndex = searchIndex
        }
        
        if iterations >= maxIterations {
            log("⚠️ Caption extraction hit safety limit")
            return []
        }
        
        let captionTracksJSON = String(html[startIndex..<endIndex])
        
        let patterns = [
            #""baseUrl"\s*:\s*"([^"]+)".*?"languageCode"\s*:\s*"([^"]+)""#,
            #""languageCode"\s*:\s*"([^"]+)".*?"baseUrl"\s*:\s*"([^"]+)""#
        ]
        
        for (patternIndex, pattern) in patterns.enumerated() {
            if let trackRegex = try? NSRegularExpression(pattern: pattern, options: .dotMatchesLineSeparators) {
                let matches = trackRegex.matches(in: captionTracksJSON, range: NSRange(captionTracksJSON.startIndex..., in: captionTracksJSON))
                
                for match in matches {
                    var urlString: String
                    var lang: String
                    
                    if patternIndex == 0 {
                        guard let urlRange = Range(match.range(at: 1), in: captionTracksJSON),
                              let langRange = Range(match.range(at: 2), in: captionTracksJSON) else { continue }
                        urlString = String(captionTracksJSON[urlRange])
                        lang = String(captionTracksJSON[langRange])
                    } else {
                        guard let langRange = Range(match.range(at: 1), in: captionTracksJSON),
                              let urlRange = Range(match.range(at: 2), in: captionTracksJSON) else { continue }
                        urlString = String(captionTracksJSON[urlRange])
                        lang = String(captionTracksJSON[langRange])
                    }
                    
                    // Unescape
                    urlString = urlString.replacingOccurrences(of: "\\u0026", with: "&")
                    urlString = urlString.replacingOccurrences(of: "\\/", with: "/")
                    
                    if urlString.hasPrefix("/") {
                        urlString = "https://www.youtube.com" + urlString
                    }
                    
                    if !tracks.contains(where: { $0.lang == lang }) {
                        tracks.append(CaptionTrack(lang: lang, baseUrl: urlString))
                    }
                }
                
                if !tracks.isEmpty { break }
            }
        }
        
        for track in tracks {
            log("Found track: \(track.lang)")
        }
        
        return tracks
    }
    
    /// Extract the 'pot' (proof of origin token) from YouTube page
    func extractPotToken(from html: String) -> String? {
        let patterns = [
            #""serviceIntegrityDimensions"\s*:\s*\{[^}]*"poToken"\s*:\s*"([^"]+)""#,
            #""poToken"\s*:\s*"([^"]+)""#,
            #""pot"\s*:\s*"([^"]+)""#,
            #"pot=([^&\"]+)"#,
            #""botguardData"\s*:\s*\{[^}]*"token"\s*:\s*"([^"]+)""#
        ]
        
        for pattern in patterns {
            if let regex = try? NSRegularExpression(pattern: pattern, options: .dotMatchesLineSeparators),
               let match = regex.firstMatch(in: html, range: NSRange(html.startIndex..., in: html)),
               let range = Range(match.range(at: 1), in: html) {
                let token = String(html[range])
                if token.count > 20 {
                    return token
                }
            }
        }
        
        return nil
    }
    
    // MARK: - Transcript Parsers
    
    /// Parse transcript from YouTube's XML format
    func parseTranscriptXML(_ data: Data) -> String? {
        guard let xmlString = String(data: data, encoding: .utf8) else { return nil }
        
        var transcript = ""
        let pattern = #"<text[^>]*>([^<]*)</text>"#
        
        if let regex = try? NSRegularExpression(pattern: pattern) {
            let matches = regex.matches(in: xmlString, range: NSRange(xmlString.startIndex..., in: xmlString))
            
            for match in matches {
                if let range = Range(match.range(at: 1), in: xmlString) {
                    var text = String(xmlString[range])
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
    
    /// Parse transcript from YouTube's JSON3 format
    func parseTranscriptJSON3(_ data: Data) -> String? {
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
    
    // MARK: - Private Helpers
    
    private func sortTracksByPreference(_ tracks: [CaptionTrack]) -> [CaptionTrack] {
        return tracks.sorted { a, b in
            let priority: (String) -> Int = { lang in
                if lang.lowercased().hasPrefix("en") && !lang.contains("auto") { return 0 }
                if lang.lowercased().hasPrefix("en") { return 1 }
                if lang.lowercased().hasPrefix("ko") && !lang.contains("auto") { return 2 }
                if lang.lowercased().hasPrefix("ko") { return 3 }
                return 4
            }
            return priority(a.lang) < priority(b.lang)
        }
    }
    
    private func log(_ message: String) {
        print("\(logPrefix) \(message)")
    }
}
