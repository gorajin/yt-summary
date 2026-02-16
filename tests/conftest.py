"""
Shared pytest fixtures and configuration.
"""

import pytest
from unittest.mock import patch


@pytest.fixture
def disable_supabase():
    """Force fallback to in-memory store by making _get_supabase return None.
    
    Reusable across any test that needs to run without a Supabase connection.
    """
    with patch("app.services.jobs._get_supabase", return_value=None):
        yield


@pytest.fixture
def sample_summary_json():
    """A realistic summary_json structure for use across test modules."""
    return {
        "title": "How React Server Components Work",
        "contentType": "tutorial",
        "overview": "A deep dive into React Server Components architecture.",
        "tableOfContents": [
            {"section": "Introduction", "timestamp": "0:00", "description": "What are RSC?"},
            {"section": "Architecture", "timestamp": "5:30", "description": "How they work internally"},
        ],
        "mainConcepts": [
            {
                "concept": "Server Components",
                "definition": "Components that render on the server and send HTML to the client.",
                "timestamp": "2:15",
                "examples": ["Page layout", "Data fetching components"]
            }
        ],
        "keyInsights": [
            {
                "insight": "Server components eliminate client-side JS bundles",
                "timestamp": "3:45",
                "context": "Reduces bundle size by up to 70%"
            },
            {
                "insight": "Client components still handle interactivity",
                "timestamp": "8:20",
                "context": "Use 'use client' directive"
            }
        ],
        "detailedNotes": [
            {
                "section": "Setup & Prerequisites",
                "timestamp": "1:00",
                "points": ["Next.js 13+ required", "React 18+ with streaming support"]
            }
        ],
        "notableQuotes": [
            "The best code is the code you never send to the client."
        ],
        "resourcesMentioned": ["Next.js documentation", "React RFC #188"],
        "actionItems": ["Migrate existing pages to server components", "Audit client bundle size"],
        "questionsRaised": ["How does caching work with server components?"]
    }


@pytest.fixture
def sample_summary_row(sample_summary_json):
    """A realistic full summary row from Supabase (includes summary_json)."""
    return {
        "id": "abc-123",
        "youtube_url": "https://youtu.be/dQw4w9WgXcQ",
        "video_id": "dQw4w9WgXcQ",
        "title": "How React Server Components Work",
        "overview": "A deep dive into React Server Components architecture.",
        "content_type": "tutorial",
        "created_at": "2026-02-08T10:00:00+09:00",
        "notion_url": "https://notion.so/page-123",
        "summary_json": sample_summary_json,
    }
