"""
Unit tests for Gemini service functions.
"""

import pytest
from app.models import ContentType
from app.services.gemini import detect_content_type


class TestDetectContentType:
    """Tests for content type detection."""
    
    def test_lecture_from_title(self):
        """Test detection of lecture from title."""
        result = detect_content_type("some transcript text", "MIT Lecture on Machine Learning")
        assert result == ContentType.LECTURE
    
    def test_lecture_from_transcript(self):
        """Test detection of lecture from transcript content."""
        transcript = "Today we'll learn about the concept of recursion in computer science. As we discussed yesterday..."
        result = detect_content_type(transcript, "Video")
        assert result == ContentType.LECTURE
    
    def test_tutorial_from_title(self):
        """Test detection of tutorial from title."""
        result = detect_content_type("some text", "Python Tutorial for Beginners")
        assert result == ContentType.TUTORIAL
    
    def test_tutorial_from_transcript(self):
        """Test detection of tutorial from transcript."""
        transcript = "In this video I'll show you step by step how to build a react app. Follow along with me..."
        result = detect_content_type(transcript, "React")
        assert result == ContentType.TUTORIAL
    
    def test_interview_from_title(self):
        """Test detection of interview/podcast from title."""
        result = detect_content_type("some text", "The Tim Ferriss Podcast - Episode 500")
        assert result == ContentType.INTERVIEW
    
    def test_interview_from_transcript(self):
        """Test detection of interview from transcript."""
        transcript = "Welcome to the show! My guest today is Elon Musk. Thanks for having me, it's great to be here."
        result = detect_content_type(transcript, "Interview")
        assert result == ContentType.INTERVIEW
    
    def test_documentary_from_title(self):
        """Test detection of documentary from title."""
        result = detect_content_type("some text", "The Story of Bitcoin Documentary")
        assert result == ContentType.DOCUMENTARY
    
    def test_documentary_from_transcript(self):
        """Test detection of documentary from transcript."""
        transcript = "This is the untold story of the history of the internet. Our investigation reveals..."
        result = detect_content_type(transcript, "Video")
        assert result == ContentType.DOCUMENTARY
    
    def test_general_fallback(self):
        """Test fallback to general for unrecognized content."""
        transcript = "Some random content that doesn't match any specific type"
        result = detect_content_type(transcript, "Some Video")
        assert result == ContentType.GENERAL


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
