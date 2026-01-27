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
    private func fetchTranscript(for url: String) async -> String? {
        // Extract video ID
        let patterns = [
            #"(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/shorts\/)([a-zA-Z0-9_-]{11})"#,
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
            print("Could not extract video ID")
            return nil
        }
        
        // Try to get transcript using YouTube's innertube API
        do {
            // First, get the video page to find available captions
            let videoPageURL = URL(string: "https://www.youtube.com/watch?v=\(id)")!
            var pageRequest = URLRequest(url: videoPageURL)
            pageRequest.setValue("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15", forHTTPHeaderField: "User-Agent")
            pageRequest.timeoutInterval = 15
            
            let (pageData, _) = try await URLSession.shared.data(for: pageRequest)
            guard let pageHTML = String(data: pageData, encoding: .utf8) else {
                print("Could not decode YouTube page")
                return nil
            }
            
            // Extract captions URL from ytInitialPlayerResponse
            if let captionsURL = extractCaptionsURL(from: pageHTML, videoId: id) {
                let (captionData, _) = try await URLSession.shared.data(from: captionsURL)
                if let transcript = parseTranscriptXML(captionData) {
                    print("Successfully fetched transcript (\(transcript.count) chars)")
                    return transcript
                }
            }
            
            print("No captions found for video")
            return nil
        } catch {
            print("Transcript fetch error: \(error.localizedDescription)")
            return nil
        }
    }
    
    /// Extract captions URL from YouTube page HTML
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
        let alert = UIAlertController(title: "✅ Saved!", message: title, preferredStyle: .alert)
        alert.addAction(UIAlertAction(title: "Done", style: .default) { [weak self] _ in
            self?.extensionContext?.completeRequest(returningItems: nil, completionHandler: nil)
        })
        present(alert, animated: true)
    }
    
    private func showError(_ message: String) {
        let alert = UIAlertController(title: "Error", message: message, preferredStyle: .alert)
        alert.addAction(UIAlertAction(title: "OK", style: .cancel) { [weak self] _ in
            self?.extensionContext?.cancelRequest(withError: NSError(domain: "WatchLater", code: 1))
        })
        present(alert, animated: true)
    }
}


// MARK: - SwiftUI Share View

struct ShareExtensionView: View {
    let url: String
    let onSave: () -> Void
    let onCancel: () -> Void
    
    @State private var isLoading = false
    
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
                    onSave()
                }) {
                    HStack {
                        if isLoading {
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
                .disabled(isLoading)
                .padding(.horizontal)
                .padding(.bottom, 20)
            }
            .padding(.vertical, 20)
            .background(Color(.systemBackground))
            .cornerRadius(20, corners: [.topLeft, .topRight])
        }
        .background(Color.black.opacity(0.3))
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
