"""
Tests for the knowledge map models and condensation logic.
"""

import pytest
from app.models import (
    KnowledgeMap, Topic, TopicFact, TopicConnection
)


# ============ Model Serialization ============

class TestTopicFact:
    def test_round_trip(self):
        fact = TopicFact(
            fact="Server components reduce bundle size by 70%",
            source_video_id="abc123",
            source_title="How RSC Work",
        )
        # TopicFact doesn't have its own to_dict/from_dict, but is tested via Topic

        assert fact.fact == "Server components reduce bundle size by 70%"
        assert fact.source_video_id == "abc123"
        assert fact.source_title == "How RSC Work"


class TestTopic:
    def test_to_dict(self):
        topic = Topic(
            name="React Architecture",
            description="Modern React patterns",
            facts=[
                TopicFact(fact="RSC reduce bundles", source_video_id="v1", source_title="Video 1"),
            ],
            related_topics=["Web Performance"],
            video_ids=["v1", "v2"],
            importance=8,
        )
        d = topic.to_dict()

        assert d["name"] == "React Architecture"
        assert d["description"] == "Modern React patterns"
        assert len(d["facts"]) == 1
        assert d["facts"][0]["fact"] == "RSC reduce bundles"
        assert d["facts"][0]["sourceVideoId"] == "v1"
        assert d["relatedTopics"] == ["Web Performance"]
        assert d["videoIds"] == ["v1", "v2"]
        assert d["importance"] == 8

    def test_from_dict(self):
        data = {
            "name": "Machine Learning",
            "description": "AI and ML topics",
            "facts": [
                {"fact": "Transformers use attention", "sourceVideoId": "ml1", "sourceTitle": "Attention Paper"}
            ],
            "relatedTopics": ["Deep Learning"],
            "videoIds": ["ml1"],
            "importance": 9,
        }
        topic = Topic.from_dict(data)

        assert topic.name == "Machine Learning"
        assert len(topic.facts) == 1
        assert topic.facts[0].fact == "Transformers use attention"
        assert topic.related_topics == ["Deep Learning"]
        assert topic.importance == 9

    def test_from_dict_defaults(self):
        """Missing fields should use defaults, not crash."""
        topic = Topic.from_dict({"name": "Minimal", "description": "Test"})

        assert topic.facts == []
        assert topic.related_topics == []
        assert topic.video_ids == []
        assert topic.importance == 5


class TestTopicConnection:
    def test_to_dict(self):
        conn = TopicConnection(
            from_topic="React",
            to_topic="Performance",
            relationship="directly improves",
        )
        d = conn.to_dict()

        assert d["from"] == "React"
        assert d["to"] == "Performance"
        assert d["relationship"] == "directly improves"

    def test_from_dict(self):
        conn = TopicConnection.from_dict({
            "from": "A", "to": "B", "relationship": "builds on"
        })

        assert conn.from_topic == "A"
        assert conn.to_topic == "B"
        assert conn.relationship == "builds on"


class TestKnowledgeMap:
    def test_to_dict(self):
        km = KnowledgeMap(
            topics=[
                Topic(name="T1", description="Topic 1", importance=7),
                Topic(name="T2", description="Topic 2", importance=3),
            ],
            connections=[
                TopicConnection(from_topic="T1", to_topic="T2", relationship="relates to"),
            ],
            total_summaries=5,
            version=2,
        )
        d = km.to_dict()

        assert d["totalSummaries"] == 5
        assert d["version"] == 2
        assert len(d["topics"]) == 2
        assert len(d["connections"]) == 1
        assert d["topics"][0]["name"] == "T1"
        assert d["connections"][0]["from"] == "T1"

    def test_from_dict(self):
        data = {
            "topics": [
                {"name": "X", "description": "Topic X", "importance": 6, "facts": [], "relatedTopics": [], "videoIds": []},
            ],
            "connections": [
                {"from": "X", "to": "Y", "relationship": "contrasts with"},
            ],
            "totalSummaries": 10,
            "version": 3,
        }
        km = KnowledgeMap.from_dict(data)

        assert len(km.topics) == 1
        assert km.topics[0].name == "X"
        assert km.total_summaries == 10
        assert km.version == 3
        assert km.connections[0].relationship == "contrasts with"

    def test_empty_map(self):
        km = KnowledgeMap()

        assert km.topics == []
        assert km.connections == []
        assert km.total_summaries == 0
        assert km.version == 1

    def test_round_trip(self):
        """Serialize and deserialize should produce equivalent objects."""
        original = KnowledgeMap(
            topics=[
                Topic(
                    name="Testing",
                    description="Software testing patterns",
                    facts=[
                        TopicFact(fact="Unit tests catch regressions", source_video_id="t1", source_title="Testing 101"),
                    ],
                    related_topics=["CI/CD"],
                    video_ids=["t1", "t2"],
                    importance=7,
                ),
            ],
            connections=[
                TopicConnection(from_topic="Testing", to_topic="CI/CD", relationship="feeds into"),
            ],
            total_summaries=15,
            version=4,
        )

        serialized = original.to_dict()
        restored = KnowledgeMap.from_dict(serialized)

        assert restored.total_summaries == original.total_summaries
        assert restored.version == original.version
        assert len(restored.topics) == len(original.topics)
        assert restored.topics[0].name == original.topics[0].name
        assert restored.topics[0].facts[0].fact == original.topics[0].facts[0].fact
        assert restored.connections[0].relationship == original.connections[0].relationship


# ============ Condensation Logic ============

class TestCondenseSummary:
    def test_condense_full_summary(self):
        from app.services.knowledge_map import _condense_summary

        summary = {
            "video_id": "abc123",
            "title": "React Deep Dive",
            "overview": "A comprehensive look at React",
            "content_type": "tutorial",
            "summary_json": {
                "title": "React Deep Dive",
                "overview": "A comprehensive look at React",
                "keyInsights": [
                    {"insight": "RSC reduce bundles", "timestamp": "2:15"},
                    {"insight": "Hydration is expensive", "timestamp": "5:00"},
                    {"insight": "Streaming SSR helps", "timestamp": "8:30"},
                    {"insight": "This should be cut", "timestamp": "12:00"},
                ],
                "mainConcepts": [
                    {"concept": "Server Components"},
                    {"concept": "Hydration"},
                ],
            },
        }

        result = _condense_summary(summary)

        assert result["videoId"] == "abc123"
        assert result["title"] == "React Deep Dive"
        assert result["overview"] == "A comprehensive look at React"
        assert len(result["keyInsights"]) == 3  # capped at 3
        assert len(result["mainConcepts"]) == 2
        assert result["keyInsights"][0] == "RSC reduce bundles"

    def test_condense_minimal_summary(self):
        from app.services.knowledge_map import _condense_summary

        summary = {"video_id": "xyz", "summary_json": {}}

        result = _condense_summary(summary)

        assert result["videoId"] == "xyz"
        assert result["title"] == "Untitled"
        assert result["keyInsights"] == []
        assert result["mainConcepts"] == []

    def test_condense_no_summary_json(self):
        from app.services.knowledge_map import _condense_summary

        summary = {"video_id": "no_json", "title": "Has Title"}

        result = _condense_summary(summary)

        assert result["title"] == "Has Title"
        assert result["keyInsights"] == []
