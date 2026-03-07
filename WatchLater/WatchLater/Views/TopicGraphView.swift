import SwiftUI

// MARK: - Topic Graph View (Force-Directed Layout)

struct TopicGraphView: View {
    let topics: [APIService.TopicData]
    let connections: [APIService.TopicConnectionData]
    @Binding var selectedTopic: APIService.TopicData?
    
    @State private var nodePositions: [String: CGPoint] = [:]
    @State private var dragOffset: CGSize = .zero
    @State private var currentDragNode: String?
    @State private var scale: CGFloat = 1.0
    @State private var offset: CGSize = .zero
    @State private var lastOffset: CGSize = .zero
    @State private var isLayoutReady = false
    
    // Color palette for topics
    private let topicColors: [Color] = [
        .purple, .blue, .red, .orange, .green,
        .pink, .cyan, .indigo, .mint, .teal,
    ]
    
    var body: some View {
        GeometryReader { geometry in
            let center = CGPoint(x: geometry.size.width / 2, y: geometry.size.height / 2)
            
            ZStack {
                // Background
                Color(.systemGroupedBackground)
                    .ignoresSafeArea()
                
                // Graph canvas
                Canvas { context, size in
                    guard isLayoutReady else { return }
                    
                    // Draw edges
                    for conn in connections {
                        guard let fromPos = nodePositions[conn.from],
                              let toPos = nodePositions[conn.to] else { continue }
                        
                        let adjustedFrom = adjustedPoint(fromPos, offset: offset, scale: scale, center: center)
                        let adjustedTo = adjustedPoint(toPos, offset: offset, scale: scale, center: center)
                        
                        var path = Path()
                        path.move(to: adjustedFrom)
                        path.addLine(to: adjustedTo)
                        
                        context.stroke(path, with: .color(.gray.opacity(0.3)), lineWidth: 1.5)
                        
                        // Relationship label at midpoint
                        let mid = CGPoint(
                            x: (adjustedFrom.x + adjustedTo.x) / 2,
                            y: (adjustedFrom.y + adjustedTo.y) / 2
                        )
                        let text = Text(conn.relationship)
                            .font(.system(size: 9))
                            .foregroundColor(.secondary)
                        context.draw(text, at: mid)
                    }
                    
                    // Draw nodes
                    for topic in topics {
                        if let resolvedView = context.resolveSymbol(id: topic.name) {
                            if let position = nodePositions[topic.name] {
                                let adjusted = adjustedPoint(position, offset: offset, scale: scale, center: center)
                                context.draw(resolvedView, at: adjusted)
                            }
                        }
                    }
                } symbols: {
                    ForEach(topics) { topic in
                        let nodeSize = nodeSizeFor(importance: topic.importance ?? 5)
                        let colorIndex = topics.firstIndex(where: { $0.name == topic.name }) ?? 0
                        TopicNode(
                            topic: topic,
                            color: topicColors[colorIndex % topicColors.count],
                            size: nodeSize
                        )
                        .tag(topic.name)
                    }
                }
                .gesture(
                    // Pan gesture & Node hit-testing drag
                    DragGesture(minimumDistance: 0)
                        .onChanged { value in
                            if let dragNode = currentDragNode {
                                // Moving a specific node
                                nodePositions[dragNode] = CGPoint(
                                    x: (value.location.x - center.x - offset.width) / scale,
                                    y: (value.location.y - center.y - offset.height) / scale
                                )
                            } else {
                                // If we just started, check if we hit a node
                                if let hitTopic = nodeAt(point: value.startLocation, scale: scale, offset: offset, center: center) {
                                    currentDragNode = hitTopic.name
                                } else {
                                    // Otherwise pan the whole canvas
                                    offset = CGSize(
                                        width: lastOffset.width + value.translation.width,
                                        height: lastOffset.height + value.translation.height
                                    )
                                }
                            }
                        }
                        .onEnded { value in
                            if let dragNode = currentDragNode {
                                // Treat very short drags as taps
                                let dist = sqrt(value.translation.width * value.translation.width + value.translation.height * value.translation.height)
                                if dist < 10 {
                                    if let tappedTopic = topics.first(where: { $0.name == dragNode }) {
                                        let impact = UIImpactFeedbackGenerator(style: .light)
                                        impact.impactOccurred()
                                        selectedTopic = tappedTopic
                                    }
                                }
                                currentDragNode = nil
                            } else {
                                lastOffset = offset
                            }
                        }
                )
            }
            .gesture(
                // Pinch to zoom
                MagnifyGesture()
                    .onChanged { value in
                        scale = max(0.3, min(3.0, value.magnification))
                    }
            )
            .onAppear {
                initializeLayout(in: geometry.size)
            }
        }
    }
    
    // MARK: - Layout
    
    private func initializeLayout(in size: CGSize) {
        guard !topics.isEmpty else { return }
        
        // Circular layout as starting position
        let radius = min(size.width, size.height) * 0.3
        
        for (index, topic) in topics.enumerated() {
            let angle = (2.0 * .pi / Double(topics.count)) * Double(index) - .pi / 2
            let x = cos(angle) * radius
            let y = sin(angle) * radius
            
            nodePositions[topic.name] = CGPoint(x: x, y: y)
        }
        
        // Run a few iterations of force-directed adjustment
        for _ in 0..<20 {
            applyForces()
        }
        
        withAnimation(.easeOut(duration: 0.5)) {
            isLayoutReady = true
        }
    }
    
    private func applyForces() {
        var forces: [String: CGPoint] = [:]
        
        // Initialize
        for topic in topics {
            forces[topic.name] = .zero
        }
        
        // Repulsion between all nodes
        for i in 0..<topics.count {
            for j in (i+1)..<topics.count {
                let nameA = topics[i].name
                let nameB = topics[j].name
                guard let posA = nodePositions[nameA],
                      let posB = nodePositions[nameB] else { continue }
                
                let dx = posA.x - posB.x
                let dy = posA.y - posB.y
                let dist = max(sqrt(dx * dx + dy * dy), 1)
                let repulsionStrength: CGFloat = 8000
                let force = repulsionStrength / (dist * dist)
                
                let fx = (dx / dist) * force
                let fy = (dy / dist) * force
                
                forces[nameA]?.x += fx
                forces[nameA]?.y += fy
                forces[nameB]?.x -= fx
                forces[nameB]?.y -= fy
            }
        }
        
        // Attraction along edges
        for conn in connections {
            guard let posA = nodePositions[conn.from],
                  let posB = nodePositions[conn.to] else { continue }
            
            let dx = posB.x - posA.x
            let dy = posB.y - posA.y
            let dist = max(sqrt(dx * dx + dy * dy), 1)
            let attractionStrength: CGFloat = 0.01
            let idealLength: CGFloat = 120
            let force = (dist - idealLength) * attractionStrength
            
            let fx = (dx / dist) * force
            let fy = (dy / dist) * force
            
            forces[conn.from]?.x += fx
            forces[conn.from]?.y += fy
            forces[conn.to]?.x -= fx
            forces[conn.to]?.y -= fy
        }
        
        // Center gravity (keep things from drifting)
        for topic in topics {
            guard let pos = nodePositions[topic.name] else { continue }
            let gravityStrength: CGFloat = 0.005
            forces[topic.name]?.x -= pos.x * gravityStrength
            forces[topic.name]?.y -= pos.y * gravityStrength
        }
        
        // Apply forces with damping
        let damping: CGFloat = 0.85
        for topic in topics {
            guard let pos = nodePositions[topic.name],
                  let force = forces[topic.name] else { continue }
            
            nodePositions[topic.name] = CGPoint(
                x: pos.x + force.x * damping,
                y: pos.y + force.y * damping
            )
        }
    }
    
    // MARK: - Helpers
    
    private func adjustedPoint(_ point: CGPoint, offset: CGSize, scale: CGFloat, center: CGPoint) -> CGPoint {
        CGPoint(
            x: center.x + point.x * scale + offset.width,
            y: center.y + point.y * scale + offset.height
        )
    }
    
    private func nodeSizeFor(importance: Int) -> CGFloat {
        let base: CGFloat = 50
        let scale: CGFloat = CGFloat(importance) * 5
        return base + scale
    }
    
    private func nodeAt(point: CGPoint, scale: CGFloat, offset: CGSize, center: CGPoint) -> APIService.TopicData? {
        // Search in reverse so nodes drawn last (on top) are hit first
        for topic in topics.reversed() {
            guard let pos = nodePositions[topic.name] else { continue }
            let adjusted = adjustedPoint(pos, offset: offset, scale: scale, center: center)
            let radius = nodeSizeFor(importance: topic.importance ?? 5) / 2
            
            let dx = point.x - adjusted.x
            let dy = point.y - adjusted.y
            if dx * dx + dy * dy <= radius * radius {
                return topic
            }
        }
        return nil
    }
}

// MARK: - Topic Node

struct TopicNode: View {
    let topic: APIService.TopicData
    let color: Color
    let size: CGFloat
    
    var body: some View {
        VStack(spacing: 4) {
            // Node circle
            ZStack {
                Circle()
                    .fill(
                        RadialGradient(
                            colors: [color.opacity(0.8), color.opacity(0.3)],
                            center: .center,
                            startRadius: 0,
                            endRadius: size / 2
                        )
                    )
                    .frame(width: size, height: size)
                    .shadow(color: color.opacity(0.3), radius: 8)
                
                // Video count badge
                if let videoIds = topic.videoIds, !videoIds.isEmpty {
                    Text("\(videoIds.count)")
                        .font(.system(size: 12, weight: .bold))
                        .foregroundStyle(.white)
                }
            }
            
            // Label
            Text(topic.name)
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(.primary)
                .lineLimit(2)
                .multilineTextAlignment(.center)
                .frame(maxWidth: size + 20)
        }
    }
}
