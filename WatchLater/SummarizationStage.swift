//
//  SummarizationStage.swift
//  WatchLater
//
//  Shared model used by both the main app (HomeViewModel) and Share Extension.
//  This file should be added to both targets in Xcode.
//

import Foundation

/// Progress stages for the summarization pipeline
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
    
    /// Estimated duration in seconds for progress bar animation
    var estimatedDuration: Double {
        switch self {
        case .fetchingTranscript: return 3.0
        case .analyzingContent: return 5.0
        case .generatingSummary: return 25.0  // Longest step (Gemini processing)
        case .savingToNotion: return 4.0
        }
    }
}
