"""
Shared utilities for the YouTube Summary API.
"""


def escape_html(text: str) -> str:
    """Escape HTML special characters for safe rendering.
    
    Used by email digest and export formatters to prevent XSS
    and ensure correct display of user-generated content.
    """
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#x27;"))
