import SwiftUI

/// Summary history view showing past summarized videos
struct HistoryView: View {
    @EnvironmentObject var authManager: AuthManager
    @State private var summaries: [SummaryHistoryItem] = []
    @State private var isLoading = true
    @State private var errorMessage: String?
    
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
                        Text("No summaries yet")
                            .font(.headline)
                        Text("Share a YouTube video to get started")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }
                    .padding()
                } else {
                    List(summaries) { summary in
                        SummaryRow(summary: summary)
                    }
                    .refreshable {
                        await loadHistory()
                    }
                }
            }
            .navigationTitle("History")
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
            summaries = try await fetchSummaries(token: token)
        } catch {
            errorMessage = error.localizedDescription
        }
        
        isLoading = false
    }
    
    private func fetchSummaries(token: String) async throws -> [SummaryHistoryItem] {
        let endpoint = URL(string: "\(APIConfig.baseURL)/summaries")!
        
        var request = URLRequest(url: endpoint)
        request.timeoutInterval = APIConfig.apiTimeout
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        
        let (data, response) = try await URLSession.shared.data(for: request)
        
        guard let httpResponse = response as? HTTPURLResponse,
              httpResponse.statusCode == 200 else {
            throw URLError(.badServerResponse)
        }
        
        return try JSONDecoder().decode([SummaryHistoryItem].self, from: data)
    }
}

// MARK: - Summary Row

struct SummaryRow: View {
    let summary: SummaryHistoryItem
    
    /// Extract video ID for thumbnail
    private var videoId: String? {
        let patterns = [
            #"(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/shorts\/)([a-zA-Z0-9_-]{11})"#,
            #"(?:youtube\.com\/embed\/)([a-zA-Z0-9_-]{11})"#
        ]
        
        for pattern in patterns {
            if let regex = try? NSRegularExpression(pattern: pattern),
               let match = regex.firstMatch(in: summary.youtubeUrl, range: NSRange(summary.youtubeUrl.startIndex..., in: summary.youtubeUrl)),
               let range = Range(match.range(at: 1), in: summary.youtubeUrl) {
                return String(summary.youtubeUrl[range])
            }
        }
        return nil
    }
    
    private var thumbnailURL: URL? {
        guard let videoId = videoId else { return nil }
        return URL(string: "https://img.youtube.com/vi/\(videoId)/mqdefault.jpg")
    }
    
    private var formattedDate: String {
        // Parse ISO 8601 date
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
            
            // Open in Notion
            if let notionUrl = summary.notionUrl,
               let url = URL(string: notionUrl) {
                Link(destination: url) {
                    Image(systemName: "arrow.up.forward.square")
                        .foregroundStyle(.blue)
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
