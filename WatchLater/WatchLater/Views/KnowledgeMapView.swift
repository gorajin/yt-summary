import SwiftUI

// MARK: - Knowledge Map View

struct KnowledgeMapView: View {
    @EnvironmentObject var authManager: AuthManager
    @State private var mapResponse: APIService.KnowledgeMapResponse?
    @State private var isLoading = false
    @State private var isBuilding = false
    @State private var buildProgress: String = ""
    @State private var errorMessage: String?
    @State private var showGraphView = false
    @State private var selectedTopic: APIService.TopicData?
    
    private var topics: [APIService.TopicData] {
        mapResponse?.knowledgeMap?.topics ?? []
    }
    
    private var connections: [APIService.TopicConnectionData] {
        mapResponse?.knowledgeMap?.connections ?? []
    }
    
    // Graph view renders only the top topics by importance to avoid iOS OOM
    private let graphTopicLimit = 25
    
    private var graphTopics: [APIService.TopicData] {
        let sorted = topics.sorted { ($0.importance ?? 5) > ($1.importance ?? 5) }
        return Array(sorted.prefix(graphTopicLimit))
    }
    
    private var graphConnections: [APIService.TopicConnectionData] {
        let graphTopicNames = Set(graphTopics.map { $0.name })
        return connections.filter { graphTopicNames.contains($0.from) && graphTopicNames.contains($0.to) }
    }
    
    var body: some View {
        NavigationStack {
            ZStack {
                Color(.systemGroupedBackground)
                    .ignoresSafeArea()
                
                if isLoading {
                    loadingView
                } else if topics.isEmpty && !isBuilding {
                    emptyStateView
                } else {
                    if showGraphView {
                        TopicGraphView(
                            topics: graphTopics,
                            connections: graphConnections,
                            selectedTopic: $selectedTopic
                        )
                    } else {
                        topicListView
                    }
                }
                
                // Building overlay
                if isBuilding {
                    buildingOverlay
                }
            }
            .navigationTitle("Knowledge Map")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    HStack(spacing: 12) {
                        if !topics.isEmpty {
                            // View toggle
                            Button(action: { withAnimation(.spring()) { showGraphView.toggle() } }) {
                                Image(systemName: showGraphView ? "list.bullet" : "circle.grid.cross")
                                    .font(.body)
                            }
                        }
                        
                        // Build / Rebuild button
                        Button(action: buildMap) {
                            Image(systemName: "arrow.triangle.2.circlepath")
                                .font(.body)
                        }
                        .disabled(isBuilding)
                    }
                }
            }
            .sheet(item: $selectedTopic) { topic in
                TopicDetailSheet(topic: topic, connections: connections)
            }
            .task {
                await loadMap()
            }
        }
    }
    
    // MARK: - Empty State
    
    private var emptyStateView: some View {
        VStack(spacing: 20) {
            Image(systemName: "map")
                .font(.system(size: 60))
                .foregroundStyle(
                    LinearGradient(colors: [.purple, .blue], startPoint: .topLeading, endPoint: .bottomTrailing)
                )
            
            Text("Build Your Knowledge Map")
                .font(.title2.bold())
            
            Text("Synthesize all your video summaries into\nan organized topic graph with connections.")
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
            
            if let msg = errorMessage {
                Text(msg)
                    .font(.caption)
                    .foregroundStyle(.red)
                    .padding(.horizontal)
            }
            
            Button(action: buildMap) {
                HStack {
                    Image(systemName: "sparkles")
                    Text("Build Knowledge Map")
                }
                .fontWeight(.semibold)
                .foregroundStyle(.white)
                .padding(.horizontal, 32)
                .padding(.vertical, 14)
                .background(
                    LinearGradient(colors: [.purple, .blue], startPoint: .leading, endPoint: .trailing)
                )
                .cornerRadius(14)
            }
            .disabled(isBuilding)
        }
        .padding()
    }
    
    // MARK: - Loading
    
    private var loadingView: some View {
        VStack(spacing: 16) {
            ProgressView()
                .scaleEffect(1.2)
            Text("Loading knowledge map...")
                .font(.subheadline)
                .foregroundStyle(.secondary)
        }
    }
    
    // MARK: - Building Overlay
    
    private var buildingOverlay: some View {
        VStack(spacing: 16) {
            ZStack {
                Circle()
                    .fill(.ultraThinMaterial)
                    .frame(width: 80, height: 80)
                
                Image(systemName: "brain.head.profile")
                    .font(.system(size: 32))
                    .foregroundStyle(
                        LinearGradient(colors: [.purple, .blue], startPoint: .topLeading, endPoint: .bottomTrailing)
                    )
                    .symbolEffect(.pulse, isActive: isBuilding)
            }
            
            Text("Building Knowledge Map...")
                .font(.headline)
            
            Text(buildProgress.isEmpty ? "Analyzing your summaries..." : buildProgress)
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
            
            ProgressView()
                .scaleEffect(0.8)
        }
        .padding(32)
        .background(.ultraThinMaterial)
        .cornerRadius(20)
        .shadow(color: .black.opacity(0.1), radius: 20)
    }
    
    // MARK: - Topic List
    
    private var topicListView: some View {
        ScrollView {
            VStack(spacing: 16) {
                // Header stats
                if let mapData = mapResponse?.knowledgeMap {
                    headerStats(mapData: mapData)
                }
                
                // Stale indicator
                if mapResponse?.isStale == true {
                    staleIndicator
                }
                
                // Topic cards
                ForEach(topics) { topic in
                    TopicCard(topic: topic) {
                        selectedTopic = topic
                    }
                }
                
                // Connections section
                if !connections.isEmpty {
                    connectionsSection
                }
            }
            .padding()
        }
        .refreshable {
            await loadMap()
        }
    }
    
    // MARK: - Header Stats
    
    private func headerStats(mapData: APIService.KnowledgeMapData) -> some View {
        HStack(spacing: 20) {
            statBadge(
                icon: "book.fill",
                value: "\(mapData.topics?.count ?? 0)",
                label: "Topics"
            )
            
            statBadge(
                icon: "arrow.triangle.branch",
                value: "\(mapData.connections?.count ?? 0)",
                label: "Connections"
            )
            
            statBadge(
                icon: "play.rectangle.fill",
                value: "\(mapData.totalSummaries ?? 0)",
                label: "Videos"
            )
        }
        .padding()
        .background(.white)
        .cornerRadius(16)
        .shadow(color: .black.opacity(0.04), radius: 8, y: 4)
    }
    
    private func statBadge(icon: String, value: String, label: String) -> some View {
        VStack(spacing: 6) {
            Image(systemName: icon)
                .font(.title3)
                .foregroundStyle(.purple)
            Text(value)
                .font(.title2.bold())
            Text(label)
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity)
    }
    
    // MARK: - Stale Indicator
    
    private var staleIndicator: some View {
        HStack {
            Image(systemName: "exclamationmark.triangle.fill")
                .foregroundStyle(.orange)
            Text("New summaries available — rebuild to update")
                .font(.caption)
                .foregroundStyle(.secondary)
            Spacer()
            Button("Rebuild") { buildMap() }
                .font(.caption.bold())
                .foregroundStyle(.purple)
        }
        .padding(12)
        .background(Color.orange.opacity(0.1))
        .cornerRadius(10)
    }
    
    // MARK: - Connections Section
    
    private var connectionsSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Image(systemName: "link")
                    .foregroundStyle(.purple)
                Text("Connections")
                    .font(.headline)
            }
            .padding(.top, 8)
            
            ForEach(connections) { conn in
                HStack(spacing: 8) {
                    Text(conn.from)
                        .font(.caption.bold())
                        .padding(.horizontal, 8)
                        .padding(.vertical, 4)
                        .background(Color.purple.opacity(0.1))
                        .cornerRadius(6)
                    
                    Image(systemName: "arrow.right")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                    
                    Text(conn.relationship)
                        .font(.caption)
                        .italic()
                        .foregroundStyle(.secondary)
                    
                    Image(systemName: "arrow.right")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                    
                    Text(conn.to)
                        .font(.caption.bold())
                        .padding(.horizontal, 8)
                        .padding(.vertical, 4)
                        .background(Color.blue.opacity(0.1))
                        .cornerRadius(6)
                }
            }
        }
        .padding()
        .background(.white)
        .cornerRadius(16)
        .shadow(color: .black.opacity(0.04), radius: 8, y: 4)
    }
    
    // MARK: - Actions
    
    private func loadMap() async {
        guard let token = authManager.accessToken else { return }
        isLoading = true
        defer { isLoading = false }
        
        do {
            mapResponse = try await APIService.shared.getKnowledgeMap(authToken: token)
        } catch {
            print("Knowledge Map: Failed to load: \(error)")
        }
    }
    
    private func buildMap() {
        guard let token = authManager.accessToken else { return }
        
        isBuilding = true
        errorMessage = nil
        buildProgress = "Starting build..."
        
        Task {
            do {
                let response = try await APIService.shared.buildKnowledgeMap(authToken: token)
                buildProgress = "Analyzing summaries..."
                
                // Poll for completion using existing poll pattern
                let result = try await pollBuild(jobId: response.jobId, authToken: token)
                
                if let mapData = result["knowledgeMap"] as? [String: Any] {
                    // Reload from API to get the full response
                    await loadMap()
                }
                
                isBuilding = false
                
            } catch {
                errorMessage = error.localizedDescription
                isBuilding = false
            }
        }
    }
    
    private func pollBuild(jobId: String, authToken: String) async throws -> [String: Any] {
        let statusURL = URL(string: "\(AppConfig.apiBaseURL)/status/\(jobId)")!
        
        for attempt in 1...120 {
            var request = URLRequest(url: statusURL)
            request.setValue("Bearer \(authToken)", forHTTPHeaderField: "Authorization")
            request.timeoutInterval = 30
            
            let (data, _) = try await URLSession.shared.data(for: request)
            
            guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let status = json["status"] as? String else {
                try await Task.sleep(nanoseconds: 3_000_000_000)
                continue
            }
            
            let stage = json["stage"] as? String ?? "Processing"
            buildProgress = stage
            
            if status == "complete" {
                return json["result"] as? [String: Any] ?? [:]
            }
            
            if status == "failed" {
                let error = json["error"] as? String ?? "Build failed"
                throw APIError.serverError(error)
            }
            
            try await Task.sleep(nanoseconds: 3_000_000_000)
        }
        
        throw APIError.serverError("Build timed out")
    }
}

// MARK: - Topic Card

struct TopicCard: View {
    let topic: APIService.TopicData
    let onTap: () -> Void
    
    var body: some View {
        Button(action: onTap) {
            VStack(alignment: .leading, spacing: 12) {
                // Header
                HStack {
                    Text(topic.name)
                        .font(.headline)
                        .foregroundStyle(.primary)
                    
                    Spacer()
                    
                    // Importance indicator
                    HStack(spacing: 2) {
                        ForEach(0..<min(topic.importance ?? 5, 10), id: \.self) { i in
                            Circle()
                                .fill(importanceColor(for: topic.importance ?? 5))
                                .frame(width: 6, height: 6)
                        }
                    }
                }
                
                // Description
                Text(topic.description)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .lineLimit(3)
                
                // Bottom bar
                HStack {
                    // Video count
                    if let videoIds = topic.videoIds, !videoIds.isEmpty {
                        Label("\(videoIds.count) video\(videoIds.count == 1 ? "" : "s")",
                              systemImage: "play.rectangle.fill")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    
                    // Fact count
                    if let facts = topic.facts, !facts.isEmpty {
                        Label("\(facts.count) fact\(facts.count == 1 ? "" : "s")",
                              systemImage: "lightbulb.fill")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    
                    Spacer()
                    
                    // Related topics chips
                    if let related = topic.relatedTopics?.prefix(2), !related.isEmpty {
                        ForEach(Array(related), id: \.self) { name in
                            Text(name)
                                .font(.caption2)
                                .padding(.horizontal, 6)
                                .padding(.vertical, 2)
                                .background(Color.purple.opacity(0.1))
                                .foregroundStyle(.purple)
                                .cornerRadius(4)
                        }
                    }
                    
                    Image(systemName: "chevron.right")
                        .font(.caption)
                        .foregroundStyle(.quaternary)
                }
            }
            .padding()
            .background(.white)
            .cornerRadius(16)
            .shadow(color: .black.opacity(0.04), radius: 8, y: 4)
        }
        .buttonStyle(.plain)
    }
    
    private func importanceColor(for importance: Int) -> Color {
        switch importance {
        case 8...10: return .red
        case 5...7: return .orange
        default: return .green
        }
    }
}

// MARK: - Topic Detail Sheet

struct TopicDetailSheet: View {
    let topic: APIService.TopicData
    let connections: [APIService.TopicConnectionData]
    @Environment(\.dismiss) var dismiss
    
    private var relevantConnections: [APIService.TopicConnectionData] {
        connections.filter { $0.from == topic.name || $0.to == topic.name }
    }
    
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    // Description
                    Text(topic.description)
                        .font(.body)
                        .foregroundStyle(.secondary)
                    
                    // Importance
                    HStack {
                        Text("Importance")
                            .font(.subheadline.bold())
                        Spacer()
                        HStack(spacing: 3) {
                            ForEach(0..<10, id: \.self) { i in
                                RoundedRectangle(cornerRadius: 2)
                                    .fill(i < (topic.importance ?? 5) ? Color.purple : Color(.systemGray5))
                                    .frame(width: 16, height: 8)
                            }
                        }
                    }
                    .padding()
                    .background(Color(.systemGray6))
                    .cornerRadius(12)
                    
                    // Key Facts
                    if let facts = topic.facts, !facts.isEmpty {
                        VStack(alignment: .leading, spacing: 12) {
                            Text("Key Facts")
                                .font(.headline)
                            
                            ForEach(facts) { fact in
                                VStack(alignment: .leading, spacing: 4) {
                                    Text("• \(fact.fact)")
                                        .font(.subheadline)
                                    
                                    if let source = fact.sourceTitle, !source.isEmpty {
                                        Text("from \(source)")
                                            .font(.caption)
                                            .foregroundStyle(.purple)
                                    }
                                }
                                .padding(.vertical, 4)
                            }
                        }
                    }
                    
                    // Connections
                    if !relevantConnections.isEmpty {
                        VStack(alignment: .leading, spacing: 12) {
                            Text("Connections")
                                .font(.headline)
                            
                            ForEach(relevantConnections) { conn in
                                HStack(spacing: 8) {
                                    let isFrom = conn.from == topic.name
                                    Text(isFrom ? conn.to : conn.from)
                                        .font(.subheadline.bold())
                                        .foregroundStyle(.purple)
                                    
                                    Text("— \(conn.relationship)")
                                        .font(.subheadline)
                                        .foregroundStyle(.secondary)
                                }
                            }
                        }
                    }
                    
                    // Related Topics
                    if let related = topic.relatedTopics, !related.isEmpty {
                        VStack(alignment: .leading, spacing: 8) {
                            Text("Related Topics")
                                .font(.headline)
                            
                            FlowLayout(spacing: 8) {
                                ForEach(related, id: \.self) { name in
                                    Text(name)
                                        .font(.caption)
                                        .padding(.horizontal, 10)
                                        .padding(.vertical, 6)
                                        .background(Color.purple.opacity(0.1))
                                        .foregroundStyle(.purple)
                                        .cornerRadius(8)
                                }
                            }
                        }
                    }
                }
                .padding()
            }
            .navigationTitle(topic.name)
            .navigationBarTitleDisplayMode(.large)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                }
            }
        }
    }
}

// MARK: - Flow Layout (for tag chips)

struct FlowLayout: Layout {
    var spacing: CGFloat = 8
    
    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let result = arrange(proposal: proposal, subviews: subviews)
        return result.size
    }
    
    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let result = arrange(proposal: ProposedViewSize(width: bounds.width, height: bounds.height), subviews: subviews)
        for (index, origin) in result.origins.enumerated() {
            subviews[index].place(at: CGPoint(x: bounds.minX + origin.x, y: bounds.minY + origin.y), proposal: .unspecified)
        }
    }
    
    private func arrange(proposal: ProposedViewSize, subviews: Subviews) -> (size: CGSize, origins: [CGPoint]) {
        var origins: [CGPoint] = []
        var x: CGFloat = 0
        var y: CGFloat = 0
        var maxHeight: CGFloat = 0
        let maxWidth = proposal.width ?? .infinity
        
        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if x + size.width > maxWidth && x > 0 {
                x = 0
                y += maxHeight + spacing
                maxHeight = 0
            }
            origins.append(CGPoint(x: x, y: y))
            maxHeight = max(maxHeight, size.height)
            x += size.width + spacing
        }
        
        return (CGSize(width: maxWidth, height: y + maxHeight), origins)
    }
}

#Preview {
    KnowledgeMapView()
        .environmentObject(AuthManager())
}
