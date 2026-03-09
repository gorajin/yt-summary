"""
Tests for the configuration module.

Verifies that environment variable parsing, CORS configuration,
and startup validation behave correctly.
"""

import pytest
from unittest.mock import patch


class TestCORSParsing:
    """Tests for ALLOWED_ORIGINS parsing from environment."""

    def test_default_allows_all(self):
        """When ALLOWED_ORIGINS is not set, should default to ['*']."""
        with patch.dict("os.environ", {}, clear=False):
            # Remove the key if it exists
            import os
            env = os.environ.copy()
            env.pop("ALLOWED_ORIGINS", None)
            with patch.dict("os.environ", env, clear=True):
                # Re-evaluate the config
                import importlib
                import app.config as cfg
                importlib.reload(cfg)
                assert cfg.ALLOWED_ORIGINS == ["*"]

    def test_single_origin(self):
        """Single origin should be parsed correctly."""
        with patch.dict("os.environ", {"ALLOWED_ORIGINS": "https://myapp.com"}):
            import importlib
            import app.config as cfg
            importlib.reload(cfg)
            assert "https://myapp.com" in cfg.ALLOWED_ORIGINS

    def test_multiple_origins(self):
        """Comma-separated origins should be split correctly."""
        with patch.dict("os.environ", {"ALLOWED_ORIGINS": "https://a.com,https://b.com,https://c.com"}):
            import importlib
            import app.config as cfg
            importlib.reload(cfg)
            assert len(cfg.ALLOWED_ORIGINS) == 3
            assert "https://a.com" in cfg.ALLOWED_ORIGINS
            assert "https://b.com" in cfg.ALLOWED_ORIGINS

    def test_origins_with_spaces(self):
        """Origins with extra spaces should be trimmed."""
        with patch.dict("os.environ", {"ALLOWED_ORIGINS": "  https://a.com , https://b.com  "}):
            import importlib
            import app.config as cfg
            importlib.reload(cfg)
            assert "https://a.com" in cfg.ALLOWED_ORIGINS
            assert "https://b.com" in cfg.ALLOWED_ORIGINS

    def test_empty_origins_defaults_to_wildcard(self):
        """Empty ALLOWED_ORIGINS should default to ['*']."""
        with patch.dict("os.environ", {"ALLOWED_ORIGINS": ""}):
            import importlib
            import app.config as cfg
            importlib.reload(cfg)
            assert cfg.ALLOWED_ORIGINS == ["*"]

    def test_whitespace_only_defaults_to_wildcard(self):
        """Whitespace-only ALLOWED_ORIGINS should default to ['*']."""
        with patch.dict("os.environ", {"ALLOWED_ORIGINS": "   "}):
            import importlib
            import app.config as cfg
            importlib.reload(cfg)
            assert cfg.ALLOWED_ORIGINS == ["*"]


class TestDeveloperUserIDs:
    """Tests for DEVELOPER_USER_IDS parsing."""

    def test_empty_dev_ids(self):
        """No developer IDs set should result in empty list."""
        with patch.dict("os.environ", {"DEVELOPER_USER_IDS": ""}):
            import importlib
            import app.config as cfg
            importlib.reload(cfg)
            assert cfg.DEVELOPER_USER_IDS == []

    def test_single_dev_id(self):
        """Single developer ID should parse correctly."""
        with patch.dict("os.environ", {"DEVELOPER_USER_IDS": "user-abc-123"}):
            import importlib
            import app.config as cfg
            importlib.reload(cfg)
            assert "user-abc-123" in cfg.DEVELOPER_USER_IDS

    def test_multiple_dev_ids(self):
        """Multiple comma-separated IDs should all be captured."""
        with patch.dict("os.environ", {"DEVELOPER_USER_IDS": "id1,id2,id3"}):
            import importlib
            import app.config as cfg
            importlib.reload(cfg)
            assert len(cfg.DEVELOPER_USER_IDS) == 3

    def test_dev_ids_with_spaces(self):
        """Developer IDs with surrounding spaces should be trimmed."""
        with patch.dict("os.environ", {"DEVELOPER_USER_IDS": " id1 , id2 "}):
            import importlib
            import app.config as cfg
            importlib.reload(cfg)
            assert "id1" in cfg.DEVELOPER_USER_IDS
            assert "id2" in cfg.DEVELOPER_USER_IDS

    def test_trailing_comma_ignored(self):
        """Trailing commas should not produce empty entries."""
        with patch.dict("os.environ", {"DEVELOPER_USER_IDS": "id1,id2,"}):
            import importlib
            import app.config as cfg
            importlib.reload(cfg)
            assert "" not in cfg.DEVELOPER_USER_IDS
            assert len(cfg.DEVELOPER_USER_IDS) == 2


class TestTierLimits:
    """Tests for tier limit constants."""

    def test_free_tier_limit_is_positive(self):
        from app.config import FREE_TIER_LIMIT
        assert FREE_TIER_LIMIT > 0

    def test_admin_tier_exceeds_free(self):
        from app.config import ADMIN_TIER_LIMIT, FREE_TIER_LIMIT
        assert ADMIN_TIER_LIMIT > FREE_TIER_LIMIT

    def test_preferred_languages_not_empty(self):
        from app.config import PREFERRED_LANGUAGES
        assert len(PREFERRED_LANGUAGES) > 0
        assert "en" in PREFERRED_LANGUAGES


class TestStartupValidation:
    """Tests for the validate_startup function."""

    def test_validate_startup_returns_bool(self):
        from app.config import validate_startup
        result = validate_startup()
        assert isinstance(result, bool)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
