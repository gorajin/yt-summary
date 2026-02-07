import SwiftUI

/// Summary history view showing past summarized videos
struct HistoryView: View {
    @EnvironmentObject var authManager: AuthManager
    @State private var summaries: [SummaryHistoryItem] = []
    @State private var isLoading = true
    @State private var errorMessage: String?
    @State private var searchText = ""
    
    var body: some View {
        NavigationStack {
            Group {
                if isLoading {
                    ProgressView("Loading history...")
                } else if let error = errorMessage {
                    VStack(spacing: 16) {
                        Image(systemName: "exclamationmark.triangle")
                            .font(.largeTitle)
                            .foregroundStyle(.orange)
                        Text(error)
                            .foregroundStyle(.secondary)
                        Button("Retry") {
                            Task { await loadHistory() }
                        }
                    }
                    .padding()
                } else if summaries.isEmpty {
                    VStack(spacing: 16) {
                        Image(systemName: "doc.text.magnifyingglass")
                            .font(.system(size: 48))
                            .foregroundStyle(.secondary)
                        Text(searchText.isEmpty ? "No summaries yet" : "No results found")
                            .font(.headline)
                        Text(searchText.isEmpty ? "Share a YouTube video to get started" : "Try a different search term")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }
                    .padding()
                } else {
                    List(summaries) { summary in
                        SummaryRow(summary: summary, onRetry: {
                            retrySummary(summary)
                        })
                    }
                    .refreshable {
                        await loadHistory()
                    }
                }
            }
            .navigationTitle("History")
            .searchable(text: $searchText, prompt: "Search summaries")
            .onSubmit(of: .search) {
                Task { await loadHistory() }
            }
            .onChange(of: searchText) { _, newValue in
                if newValue.isEmpty {
                    Task { await loadHistory() }
                }
            }
            .onAppear {
                Task { await loadHistory() }
            }
        }
    }
    
    private func loadHistory() async {
        isLoading = true
        errorMessage = nil
        
        guard let token = authManager.accessToken else {
            errorMessage = "Please sign in"
            isLoading = false
            return
        }
        
        do {
            summaries = try await fetchSummaries(token: token, query: searchText.isEmpty ? nil : searchText)
        } catch {
            errorMessage = error.localizedDescription
        }
        
        isLoading = false
    }
    
    private func fetchSummaries(token: String, query: String? = nil) async throws -> [SummaryHistoryItem] {
        var urlString = "\(AppConfig.apiBaseURL)/summaries"
        
        // Add search query if present
        if let query = query, !query.isEmpty {
            let encoded = query.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? query
            urlString += "?q=\(encoded)"
        }
        
        let endpoint = URL(string: urlString)!
        
        var request = URLRequest(url: endpoint)
        request.timeoutInterval = AppConfig.apiTimeout
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        
        let (data, response) = try await URLSession.shared.data(for: request)
        
        guard let httpResponse = response as? HTTPURLResponse,
              httpResponse.statusCode == 200 else {
            throw URLError(.badServerResponse)
        }
        
        return try JSONDecoder().decode([SummaryHistoryItem].self, from: data)
    }
    
    private func retrySummary(_ summary: SummaryHistoryItem) {
        // Copy URL to clipboard and switch to home tab for re-summarization
        UIPasteboard.general.string = summary.youtubeUrl
        // Post notification to trigger summarization from HomeView
        NotificationCenter.default.post(
            name: NSNotification.Name("RetrySummary"),
            object: nil,
            userInfo: ["url": summary.youtubeUrl]
        )
    }
}

// MARK: - Summary Row

struct SummaryRow: View {
    let summary: SummaryHistoryItem
    var onRetry: (() -> Void)? = nil
    
    /// Extract video ID for thumbnail (uses shared logic)
    private var videoId: String? {
        TranscriptExtractor.extractVideoId(from: summary.youtubeUrl)
    }
    
    private var thumbnailURL: URL? {
        guard let videoId = videoId else { return nil }
        return URL(string: "https://img.youtube.com/vi/\(videoId)/mqdefault.jpg")
    }
    
    private var formattedDate: String {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        
        if let date = formatter.date(from: summary.createdAt) {
            let displayFormatter = DateFormatter()
            displayFormatter.dateStyle = .medium
            displayFormatter.timeStyle = .short
            return displayFormatter.string(from: date)
        }
        return summary.createdAt
    }
    
    var body: some View {
        HStack(spacing: 12) {
            // Thumbnail
            if let thumbnailURL = thumbnailURL {
                AsyncImage(url: thumbnailURL) { phase in
                    switch phase {
                    case .success(let image):
                        image
                            .resizable()
                            .aspectRatio(16/9, contentMode: .fill)
                            .frame(width: 80, height: 45)
                            .cornerRadius(6)
                    default:
                        thumbnailPlaceholder
                    }
                }
            } else {
                thumbnailPlaceholder
            }
            
            VStack(alignment: .leading, spacing: 4) {
                Text(summary.title ?? "Untitled")
                    .font(.subheadline)
                    .fontWeight(.medium)
                    .lineLimit(2)
                
                Text(formattedDate)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            
            Spacer()
            
            // Open in Notion or Retry
            if let notionUrl = summary.notionUrl,
               let url = URL(string: notionUrl) {
                Link(destination: url) {
                    Image(systemName: "arrow.up.forward.square")
                        .foregroundStyle(.blue)
                }
                .buttonStyle(.plain)
            } else if let onRetry = onRetry {
                Button(action: onRetry) {
                    Image(systemName: "arrow.clockwise")
                        .foregroundStyle(.orange)
                }
                .buttonStyle(.plain)
            }
        }
        .padding(.vertical, 4)
    }
    
    private var thumbnailPlaceholder: some View {
        Rectangle()
            .fill(Color(.systemGray5))
            .frame(width: 80, height: 45)
            .cornerRadius(6)
            .overlay(
                Image(systemName: "play.rectangle.fill")
                    .foregroundStyle(.red)
            )
    }
}

// MARK: - Models

struct SummaryHistoryItem: Codable, Identifiable {
    let id: String
    let youtubeUrl: String
    let title: String?
    let notionUrl: String?
    let createdAt: String
    
    enum CodingKeys: String, CodingKey {
        case id
        case youtubeUrl = "youtube_url"
        case title
        case notionUrl = "notion_url"
        case createdAt = "created_at"
    }
}

#Preview {
    HistoryView()
        .environmentObject(AuthManager())
}
