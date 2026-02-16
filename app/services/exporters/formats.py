"""
Export engine for converting stored summary_json to various output formats.

Supports: markdown, html, text
All exporters take a summary dict (from Supabase) and return formatted string content.
"""

from typing import Optional

from app.utils import escape_html as _esc


def _timestamp_to_youtube_link(timestamp: str, video_id: str) -> str:
    """Convert 'MM:SS' or 'HH:MM:SS' to a YouTube deep link."""
    if not video_id or not timestamp:
        return ""
    try:
        parts = timestamp.strip().split(":")
        if len(parts) == 2:
            seconds = int(parts[0]) * 60 + int(parts[1])
        elif len(parts) == 3:
            seconds = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        else:
            return ""
        return f"https://youtu.be/{video_id}?t={seconds}"
    except (ValueError, IndexError):
        return ""


# ============ Markdown Export (Obsidian, Bear, Logseq, etc.) ============

def export_markdown(summary: dict, video_id: Optional[str] = None) -> str:
    """Export summary as Obsidian-compatible markdown with YAML frontmatter."""
    sj = summary.get("summary_json") or {}
    title = sj.get("title") or summary.get("title", "Untitled")
    overview = sj.get("overview") or summary.get("overview", "")
    content_type = sj.get("contentType") or summary.get("content_type", "general")
    vid = video_id or summary.get("video_id", "")
    youtube_url = summary.get("youtube_url", "")
    created_at = summary.get("created_at", "")[:10]  # Just the date

    lines = []

    # YAML frontmatter (Obsidian-compatible)
    lines.append("---")
    lines.append(f"title: \"{title}\"")
    lines.append(f"type: {content_type}")
    lines.append(f"source: {youtube_url}")
    lines.append(f"date: {created_at}")
    lines.append("tags: [watchlater, video-notes]")
    lines.append("---")
    lines.append("")

    # Title and overview
    lines.append(f"# {title}")
    lines.append("")
    if overview:
        lines.append(f"> {overview}")
        lines.append("")
    if youtube_url:
        lines.append(f"🔗 [Watch Video]({youtube_url})")
        lines.append("")

    # Table of Contents
    toc = sj.get("tableOfContents", [])
    if toc:
        lines.append("## 📑 Table of Contents")
        lines.append("")
        for item in toc:
            if isinstance(item, dict):
                section = item.get("section", "")
                ts = item.get("timestamp", "")
                desc = item.get("description", "")
                link = _timestamp_to_youtube_link(ts, vid)
                ts_part = f"[{ts}]({link}) " if link else (f"[{ts}] " if ts else "")
                desc_part = f" — {desc}" if desc else ""
                lines.append(f"- {ts_part}{section}{desc_part}")
        lines.append("")

    # Main Concepts
    concepts = sj.get("mainConcepts", [])
    if concepts:
        lines.append("## 🧠 Main Concepts")
        lines.append("")
        for c in concepts:
            if isinstance(c, dict):
                name = c.get("concept", "")
                defn = c.get("definition", "")
                ts = c.get("timestamp", "")
                examples = c.get("examples", [])
                link = _timestamp_to_youtube_link(ts, vid)
                ts_part = f" ([{ts}]({link}))" if link else (f" [{ts}]" if ts else "")
                lines.append(f"### 📌 {name}{ts_part}")
                if defn:
                    lines.append(f"{defn}")
                for ex in examples:
                    lines.append(f"- *Example:* {ex}")
                lines.append("")

    # Key Insights
    insights = sj.get("keyInsights", [])
    if insights:
        lines.append("## 💡 Key Insights")
        lines.append("")
        for i in insights:
            if isinstance(i, dict):
                text = i.get("insight", str(i))
                ctx = i.get("context", "")
                ts = i.get("timestamp", "")
                link = _timestamp_to_youtube_link(ts, vid)
                ts_part = f"[{ts}]({link}) " if link else (f"[{ts}] " if ts else "")
                lines.append(f"- {ts_part}**{text}**")
                if ctx:
                    lines.append(f"  - {ctx}")
            else:
                lines.append(f"- {i}")
        lines.append("")

    # Detailed Notes
    notes = sj.get("detailedNotes", [])
    if notes:
        lines.append("## 📝 Detailed Notes")
        lines.append("")
        for section in notes:
            if isinstance(section, dict):
                sec_name = section.get("section", "Section")
                points = section.get("points", [])
                lines.append(f"### {sec_name}")
                for p in points:
                    lines.append(f"- {p}")
                lines.append("")

    # Notable Quotes
    quotes = sj.get("notableQuotes", [])
    if quotes:
        lines.append("## 💬 Notable Quotes")
        lines.append("")
        for q in quotes:
            lines.append(f"> {q}")
            lines.append("")

    # Resources
    resources = sj.get("resourcesMentioned", [])
    if resources:
        lines.append("## 🔗 Resources Mentioned")
        lines.append("")
        for r in resources:
            lines.append(f"- {r}")
        lines.append("")

    # Action Items
    actions = sj.get("actionItems", [])
    if actions:
        lines.append("## ✅ Action Items")
        lines.append("")
        for a in actions:
            lines.append(f"- [ ] {a}")
        lines.append("")

    # Questions
    questions = sj.get("questionsRaised", [])
    if questions:
        lines.append("## ❓ Questions to Explore")
        lines.append("")
        for q in questions:
            lines.append(f"- {q}")
        lines.append("")

    return "\n".join(lines)


# ============ HTML Export (Apple Notes, email) ============

def export_html(summary: dict, video_id: Optional[str] = None) -> str:
    """Export summary as styled HTML for Apple Notes and email embedding."""
    sj = summary.get("summary_json") or {}
    title = sj.get("title") or summary.get("title", "Untitled")
    overview = sj.get("overview") or summary.get("overview", "")
    vid = video_id or summary.get("video_id", "")
    youtube_url = summary.get("youtube_url", "")

    parts = []
    parts.append(f"<h1>{_esc(title)}</h1>")
    
    if overview:
        parts.append(f'<blockquote style="border-left:4px solid #4A90D9;padding:8px 16px;margin:16px 0;background:#f0f7ff;border-radius:4px;">{_esc(overview)}</blockquote>')
    
    if youtube_url:
        parts.append(f'<p>🔗 <a href="{youtube_url}">Watch Video</a></p>')

    # Key Insights
    insights = sj.get("keyInsights", [])
    if insights:
        parts.append("<h2>💡 Key Insights</h2>")
        parts.append("<ul>")
        for i in insights:
            if isinstance(i, dict):
                text = i.get("insight", str(i))
                ts = i.get("timestamp", "")
                link = _timestamp_to_youtube_link(ts, vid)
                ts_html = f'<a href="{link}" style="color:#4A90D9;">[{ts}]</a> ' if link else (f"[{ts}] " if ts else "")
                parts.append(f"<li>{ts_html}<strong>{_esc(text)}</strong></li>")
            else:
                parts.append(f"<li>{_esc(str(i))}</li>")
        parts.append("</ul>")

    # Main Concepts
    concepts = sj.get("mainConcepts", [])
    if concepts:
        parts.append("<h2>🧠 Main Concepts</h2>")
        for c in concepts:
            if isinstance(c, dict):
                name = c.get("concept", "")
                defn = c.get("definition", "")
                parts.append(f"<h3>📌 {_esc(name)}</h3>")
                if defn:
                    parts.append(f"<p>{_esc(defn)}</p>")

    # Detailed Notes
    notes = sj.get("detailedNotes", [])
    if notes:
        parts.append("<h2>📝 Detailed Notes</h2>")
        for section in notes:
            if isinstance(section, dict):
                sec_name = section.get("section", "")
                points = section.get("points", [])
                parts.append(f"<h3>{_esc(sec_name)}</h3>")
                if points:
                    parts.append("<ul>")
                    for p in points:
                        parts.append(f"<li>{_esc(str(p))}</li>")
                    parts.append("</ul>")

    # Notable Quotes
    quotes = sj.get("notableQuotes", [])
    if quotes:
        parts.append("<h2>💬 Notable Quotes</h2>")
        for q in quotes:
            parts.append(f'<blockquote style="border-left:3px solid #ccc;padding:4px 12px;margin:8px 0;font-style:italic;">{_esc(str(q))}</blockquote>')

    # Action Items
    actions = sj.get("actionItems", [])
    if actions:
        parts.append("<h2>✅ Action Items</h2>")
        parts.append("<ul>")
        for a in actions:
            parts.append(f"<li>☐ {_esc(str(a))}</li>")
        parts.append("</ul>")

    return "\n".join(parts)


# _esc is imported from app.utils.escape_html at the top of this file


# ============ Plain Text Export (Clipboard) ============

def export_text(summary: dict, video_id: Optional[str] = None) -> str:
    """Export summary as clean plain text for clipboard."""
    sj = summary.get("summary_json") or {}
    title = sj.get("title") or summary.get("title", "Untitled")
    overview = sj.get("overview") or summary.get("overview", "")
    youtube_url = summary.get("youtube_url", "")

    lines = []
    lines.append(title.upper())
    lines.append("=" * len(title))
    lines.append("")
    
    if overview:
        lines.append(overview)
        lines.append("")
    
    if youtube_url:
        lines.append(f"Source: {youtube_url}")
        lines.append("")

    # Key Insights
    insights = sj.get("keyInsights", [])
    if insights:
        lines.append("KEY INSIGHTS")
        lines.append("-" * 12)
        for idx, i in enumerate(insights, 1):
            if isinstance(i, dict):
                text = i.get("insight", str(i))
                lines.append(f"  {idx}. {text}")
            else:
                lines.append(f"  {idx}. {i}")
        lines.append("")

    # Main Concepts
    concepts = sj.get("mainConcepts", [])
    if concepts:
        lines.append("MAIN CONCEPTS")
        lines.append("-" * 13)
        for c in concepts:
            if isinstance(c, dict):
                name = c.get("concept", "")
                defn = c.get("definition", "")
                lines.append(f"  • {name}")
                if defn:
                    lines.append(f"    {defn}")
        lines.append("")

    # Detailed Notes
    notes = sj.get("detailedNotes", [])
    if notes:
        lines.append("DETAILED NOTES")
        lines.append("-" * 14)
        for section in notes:
            if isinstance(section, dict):
                sec_name = section.get("section", "")
                points = section.get("points", [])
                lines.append(f"  [{sec_name}]")
                for p in points:
                    lines.append(f"    • {p}")
        lines.append("")

    # Notable Quotes
    quotes = sj.get("notableQuotes", [])
    if quotes:
        lines.append("NOTABLE QUOTES")
        lines.append("-" * 14)
        for q in quotes:
            lines.append(f'  "{q}"')
        lines.append("")

    # Action Items
    actions = sj.get("actionItems", [])
    if actions:
        lines.append("ACTION ITEMS")
        lines.append("-" * 12)
        for a in actions:
            lines.append(f"  [ ] {a}")
        lines.append("")

    return "\n".join(lines)


# ============ Router dispatch ============

EXPORTERS = {
    "markdown": export_markdown,
    "md": export_markdown,
    "html": export_html,
    "text": export_text,
    "txt": export_text,
}

CONTENT_TYPES = {
    "markdown": "text/markdown",
    "md": "text/markdown",
    "html": "text/html",
    "text": "text/plain",
    "txt": "text/plain",
}


def export_summary(summary: dict, fmt: str = "markdown", video_id: Optional[str] = None) -> tuple[str, str]:
    """Export a summary in the requested format.
    
    Args:
        summary: Full summary row from Supabase (must include summary_json)
        fmt: Export format (markdown, html, text)
        video_id: Optional YouTube video ID for timestamp links
        
    Returns:
        Tuple of (content, content_type)
        
    Raises:
        ValueError: If format is not supported
    """
    exporter = EXPORTERS.get(fmt.lower())
    if not exporter:
        raise ValueError(f"Unsupported export format: {fmt}. Supported: {list(EXPORTERS.keys())}")
    
    content = exporter(summary, video_id=video_id)
    content_type = CONTENT_TYPES.get(fmt.lower(), "text/plain")
    
    return content, content_type
