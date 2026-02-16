"""
Notion integration service.

Provides functions for creating Notion pages with formatted lecture notes
and legacy summary formats.
"""

from datetime import date
from notion_client import Client as NotionClient

from ..models import ContentType, LectureNotes, KnowledgeMap


def create_notion_page(notion_token: str, database_id: str, title: str, url: str, 
                       one_liner: str, takeaways: list, insights: list) -> str:
    """Create a Notion page with the summary using user's token.
    Legacy function kept for backward compatibility."""
    notion = NotionClient(auth=notion_token)
    
    children = [
        {
            "object": "block",
            "type": "callout",
            "callout": {
                "rich_text": [{"type": "text", "text": {"content": one_liner}}],
                "icon": {"emoji": "💡"},
                "color": "blue_background"
            }
        },
        {"object": "block", "type": "divider", "divider": {}},
        {
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🎯 Key Takeaways"}}]}
        },
    ]
    
    for takeaway in takeaways:
        children.append({
            "object": "block",
            "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": takeaway}}]}
        })
    
    children.append({"object": "block", "type": "divider", "divider": {}})
    children.append({
        "object": "block",
        "type": "heading_2",
        "heading_2": {"rich_text": [{"type": "text", "text": {"content": "✨ Notable Insights"}}]}
    })
    
    for insight in insights:
        children.append({
            "object": "block",
            "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": insight}}]}
        })
    
    response = notion.pages.create(
        parent={"database_id": database_id},
        properties={
            "Title": {"title": [{"text": {"content": title}}]},
            "URL": {"url": url},
            "Date Added": {"date": {"start": date.today().isoformat()}}
        },
        children=children
    )
    
    return response["url"]


def _timestamp_to_link(timestamp_str: str, video_id: str) -> str:
    """Convert 'MM:SS' or 'HH:MM:SS' to YouTube URL with timestamp."""
    if not video_id or not timestamp_str:
        return ""
    try:
        parts = timestamp_str.replace(" ", "").split(":")
        if len(parts) == 2:  # MM:SS
            seconds = int(parts[0]) * 60 + int(parts[1])
        elif len(parts) == 3:  # HH:MM:SS
            seconds = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        else:
            return ""
        return f"https://youtu.be/{video_id}?t={seconds}"
    except (ValueError, IndexError):
        return ""


def create_lecture_notes_page(notion_token: str, database_id: str, 
                               notes: LectureNotes, video_url: str,
                               video_id: str = "") -> str:
    """Create a comprehensive Notion page with rich lecture notes formatting.
    
    Uses toggle blocks for collapsible sections, callouts for key insights,
    and organized structure based on content type. Includes clickable
    YouTube timestamp links when video_id is provided.
    """
    notion = NotionClient(auth=notion_token)
    
    # Content type icons
    type_icons = {
        ContentType.LECTURE: "📚",
        ContentType.INTERVIEW: "🎙️",
        ContentType.TUTORIAL: "🔧",
        ContentType.DOCUMENTARY: "🎬",
        ContentType.GENERAL: "📝"
    }
    
    children = []
    
    # 1. Overview callout
    children.append({
        "object": "block",
        "type": "callout",
        "callout": {
            "rich_text": [{"type": "text", "text": {"content": notes.overview}}],
            "icon": {"emoji": type_icons.get(notes.content_type, "📝")},
            "color": "blue_background"
        }
    })
    
    # 2. Table of Contents (if available) - with clickable timestamp links
    if notes.table_of_contents:
        children.append({"object": "block", "type": "divider", "divider": {}})
        children.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": "📑 Table of Contents"}}]}
        })
        for item in notes.table_of_contents[:10]:
            section = item.get("section", "") if isinstance(item, dict) else str(item)
            timestamp = item.get("timestamp", "") if isinstance(item, dict) else ""
            desc = item.get("description", "") if isinstance(item, dict) else ""
            
            rich_text_parts = []
            if timestamp and video_id:
                link = _timestamp_to_link(timestamp, video_id)
                if link:
                    rich_text_parts.append({
                        "type": "text",
                        "text": {"content": f"[{timestamp}] ", "link": {"url": link}},
                        "annotations": {"color": "blue"}
                    })
            rich_text_parts.append({"type": "text", "text": {"content": section}})
            if desc:
                rich_text_parts.append({
                    "type": "text",
                    "text": {"content": f" - {desc}"},
                    "annotations": {"color": "gray"}
                })
            
            children.append({
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": rich_text_parts}
            })
    
    # 3. Main Concepts
    if notes.main_concepts:
        children.append({"object": "block", "type": "divider", "divider": {}})
        children.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🧠 Main Concepts"}}]}
        })
        for concept in notes.main_concepts[:12]:
            if isinstance(concept, dict):
                concept_name = concept.get("concept", "Concept")
                definition = concept.get("definition", "")
                examples = concept.get("examples", [])
                timestamp = concept.get("timestamp", "")
                
                toggle_header = []
                if timestamp and video_id:
                    link = _timestamp_to_link(timestamp, video_id)
                    if link:
                        toggle_header.append({
                            "type": "text",
                            "text": {"content": f"[{timestamp}] ", "link": {"url": link}},
                            "annotations": {"color": "blue"}
                        })
                toggle_header.append({
                    "type": "text",
                    "text": {"content": f"📌 {concept_name}"},
                    "annotations": {"bold": True}
                })
                
                toggle_content = []
                if definition:
                    toggle_content.append({
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {"rich_text": [{"type": "text", "text": {"content": definition}}]}
                    })
                for ex in examples[:3]:
                    toggle_content.append({
                        "object": "block",
                        "type": "bulleted_list_item",
                        "bulleted_list_item": {"rich_text": [
                            {"type": "text", "text": {"content": "Example: "}, "annotations": {"bold": True}},
                            {"type": "text", "text": {"content": str(ex)}}
                        ]}
                    })
                
                children.append({
                    "object": "block",
                    "type": "toggle",
                    "toggle": {
                        "rich_text": toggle_header,
                        "children": toggle_content if toggle_content else [
                            {"object": "block", "type": "paragraph", "paragraph": {"rich_text": []}}
                        ]
                    }
                })
            else:
                children.append({
                    "object": "block",
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": str(concept)}}]}
                })
    
    # 4. Key Insights
    if notes.key_insights:
        children.append({"object": "block", "type": "divider", "divider": {}})
        children.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": "💡 Key Insights"}}]}
        })
        for insight in notes.key_insights[:15]:
            if isinstance(insight, dict):
                insight_text = insight.get("insight", str(insight))
                context = insight.get("context", "")
                timestamp = insight.get("timestamp", "")
                
                rich_text_parts = []
                if timestamp and video_id:
                    link = _timestamp_to_link(timestamp, video_id)
                    if link:
                        rich_text_parts.append({
                            "type": "text",
                            "text": {"content": f"⏱️ {timestamp} ", "link": {"url": link}},
                            "annotations": {"color": "blue", "bold": True}
                        })
                rich_text_parts.append({"type": "text", "text": {"content": insight_text}})
                if context:
                    rich_text_parts.append({
                        "type": "text",
                        "text": {"content": f"\n{context}"},
                        "annotations": {"color": "gray"}
                    })
            else:
                rich_text_parts = [{"type": "text", "text": {"content": str(insight)}}]
            
            children.append({
                "object": "block",
                "type": "callout",
                "callout": {
                    "rich_text": rich_text_parts,
                    "icon": {"emoji": "💡"},
                    "color": "yellow_background"
                }
            })
    
    # 5. Detailed Notes
    if notes.detailed_notes:
        children.append({"object": "block", "type": "divider", "divider": {}})
        children.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": "📝 Detailed Notes"}}]}
        })
        for section in notes.detailed_notes[:8]:
            if isinstance(section, dict):
                section_name = section.get("section", "Section")
                points = section.get("points", [])
                
                children.append({
                    "object": "block",
                    "type": "heading_3",
                    "heading_3": {"rich_text": [{"type": "text", "text": {"content": section_name}}]}
                })
                for point in points[:10]:
                    children.append({
                        "object": "block",
                        "type": "bulleted_list_item",
                        "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": str(point)}}]}
                    })
    
    # 6. Notable Quotes
    if notes.notable_quotes:
        children.append({"object": "block", "type": "divider", "divider": {}})
        children.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": "💬 Notable Quotes"}}]}
        })
        for quote in notes.notable_quotes[:8]:
            children.append({
                "object": "block",
                "type": "quote",
                "quote": {"rich_text": [{"type": "text", "text": {"content": str(quote)}}]}
            })
    
    # 7. Resources Mentioned
    if notes.resources_mentioned:
        children.append({"object": "block", "type": "divider", "divider": {}})
        children.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🔗 Resources Mentioned"}}]}
        })
        for resource in notes.resources_mentioned[:10]:
            children.append({
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": str(resource)}}]}
            })
    
    # 8. Action Items
    if notes.action_items:
        children.append({"object": "block", "type": "divider", "divider": {}})
        children.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": "✅ Action Items"}}]}
        })
        for action in notes.action_items[:8]:
            children.append({
                "object": "block",
                "type": "to_do",
                "to_do": {
                    "rich_text": [{"type": "text", "text": {"content": str(action)}}],
                    "checked": False
                }
            })
    
    # 9. Questions Raised
    if notes.questions_raised:
        children.append({"object": "block", "type": "divider", "divider": {}})
        children.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": "❓ Questions to Explore"}}]}
        })
        for question in notes.questions_raised[:5]:
            children.append({
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": str(question)}}]}
            })
    
    # Notion has a limit of 100 blocks per API request
    # For long videos, we need to create the page with initial blocks,
    # then append additional blocks in subsequent requests
    BATCH_SIZE = 100
    
    # Split children into batches
    first_batch = children[:BATCH_SIZE]
    remaining_batches = [
        children[i:i + BATCH_SIZE] 
        for i in range(BATCH_SIZE, len(children), BATCH_SIZE)
    ]
    
    # Log if we have multiple batches
    total_blocks = len(children)
    if remaining_batches:
        print(f"  → Notion: {total_blocks} blocks, splitting into {1 + len(remaining_batches)} batches")
    
    # Create page with first batch
    response = notion.pages.create(
        parent={"database_id": database_id},
        properties={
            "Title": {"title": [{"text": {"content": notes.title}}]},
            "URL": {"url": video_url},
            "Date Added": {"date": {"start": date.today().isoformat()}}
        },
        children=first_batch
    )
    
    page_id = response["id"]
    page_url = response["url"]
    
    # Append remaining batches if any
    if remaining_batches:
        appended_blocks = len(first_batch)
        for batch_num, batch in enumerate(remaining_batches, start=2):
            try:
                notion.blocks.children.append(
                    block_id=page_id,
                    children=batch
                )
                appended_blocks += len(batch)
                print(f"  → Notion: Appended batch {batch_num}/{1 + len(remaining_batches)} ({len(batch)} blocks)")
            except Exception as e:
                # Log error but don't crash - page exists with partial content
                print(f"  → Notion: Failed to append batch {batch_num}: {type(e).__name__}: {e}")
                # Add a note that content was truncated
                try:
                    notion.blocks.children.append(
                        block_id=page_id,
                        children=[{
                            "object": "block",
                            "type": "callout",
                            "callout": {
                                "rich_text": [{"type": "text", "text": {"content": f"Note: Some content could not be saved ({total_blocks - appended_blocks} blocks). View the video for complete content."}}],
                                "icon": {"emoji": "⚠️"},
                                "color": "gray_background"
                            }
                        }]
                    )
                except Exception:
                    pass  # Best effort - don't fail if we can't add the warning
                break  # Stop trying additional batches after a failure
        
        print(f"  → Notion: Successfully saved {appended_blocks}/{total_blocks} blocks")
    
    return page_url


def create_knowledge_map_page(notion_token: str, database_id: str,
                               knowledge_map: KnowledgeMap) -> str:
    """Create a Notion page with the user's knowledge map.
    
    Each topic becomes a toggle block containing its description, facts
    (with source video attribution), and related topics.
    
    Returns:
        URL of the created Notion page
    """
    notion = NotionClient(auth=notion_token)
    today_str = date.today().strftime("%Y-%m-%d")
    
    topic_count = len(knowledge_map.topics)
    title_text = f"🗺️ Knowledge Map — {today_str}"
    
    # Create the page
    page = notion.pages.create(
        parent={"database_id": database_id},
        properties={
            "Title": {"title": [{"text": {"content": title_text}}]},
            "Type": {"select": {"name": "General"}},
            "Date Added": {"date": {"start": today_str}},
        },
    )
    
    page_id = page["id"]
    page_url = page.get("url", "")
    
    # Build blocks
    blocks = []
    
    # Header callout
    blocks.append({
        "object": "block",
        "type": "callout",
        "callout": {
            "rich_text": [{"type": "text", "text": {"content": 
                f"Knowledge map synthesized from {knowledge_map.total_summaries} videos • "
                f"{topic_count} topics discovered"
            }}],
            "icon": {"emoji": "🧠"},
            "color": "blue_background",
        }
    })
    
    # Divider
    blocks.append({"object": "block", "type": "divider", "divider": {}})
    
    # Topics section header
    blocks.append({
        "object": "block",
        "type": "heading_2",
        "heading_2": {
            "rich_text": [{"type": "text", "text": {"content": "📚 Topics"}}],
        }
    })
    
    # Each topic as a toggle block
    for topic in knowledge_map.topics:
        # Importance badge
        importance_bar = "🟢" * min(topic.importance, 10)
        
        # Toggle heading: Topic Name (importance)
        toggle_children = []
        
        # Description
        toggle_children.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [
                    {"type": "text", "text": {"content": topic.description},
                     "annotations": {"italic": True, "color": "gray"}},
                ],
            }
        })
        
        # Facts with source attribution
        if topic.facts:
            toggle_children.append({
                "object": "block",
                "type": "heading_3",
                "heading_3": {
                    "rich_text": [{"type": "text", "text": {"content": "Key Facts"}}],
                }
            })
            
            for fact in topic.facts[:10]:  # Cap at 10 facts per topic
                source_text = f" — {fact.source_title}" if fact.source_title else ""
                # Fact as bulleted list with source
                rich_text = [
                    {"type": "text", "text": {"content": fact.fact}},
                ]
                if source_text:
                    rich_text.append({
                        "type": "text",
                        "text": {"content": source_text},
                        "annotations": {"italic": True, "color": "gray"},
                    })
                
                toggle_children.append({
                    "object": "block",
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {"rich_text": rich_text},
                })
        
        # Related topics
        if topic.related_topics:
            related_text = "Related: " + ", ".join(topic.related_topics)
            toggle_children.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {"type": "text", "text": {"content": related_text},
                         "annotations": {"color": "purple"}},
                    ],
                }
            })
        
        # Videos count
        if topic.video_ids:
            toggle_children.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {"type": "text", "text": {"content": f"📹 Discussed in {len(topic.video_ids)} video(s)"},
                         "annotations": {"color": "gray"}},
                    ],
                }
            })
        
        # The toggle block itself
        blocks.append({
            "object": "block",
            "type": "toggle",
            "toggle": {
                "rich_text": [
                    {"type": "text", "text": {"content": f"{topic.name} "},
                     "annotations": {"bold": True}},
                    {"type": "text", "text": {"content": f" {importance_bar}"}},
                ],
                "children": toggle_children,
            }
        })
    
    # Connections section
    if knowledge_map.connections:
        blocks.append({"object": "block", "type": "divider", "divider": {}})
        blocks.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {
                "rich_text": [{"type": "text", "text": {"content": "🔗 Connections"}}],
            }
        })
        
        for conn in knowledge_map.connections:
            blocks.append({
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {
                    "rich_text": [
                        {"type": "text", "text": {"content": conn.from_topic},
                         "annotations": {"bold": True}},
                        {"type": "text", "text": {"content": f" → {conn.relationship} → "}},
                        {"type": "text", "text": {"content": conn.to_topic},
                         "annotations": {"bold": True}},
                    ],
                }
            })
    
    # Append blocks in batches (Notion limit: 100 blocks per request)
    batch_size = 100
    for i in range(0, len(blocks), batch_size):
        batch = blocks[i:i + batch_size]
        try:
            notion.blocks.children.append(block_id=page_id, children=batch)
        except Exception as e:
            print(f"  → Notion: Error appending batch {i // batch_size + 1}: {e}")
            break
    
    print(f"  → Notion: Knowledge map page created with {len(blocks)} blocks")
    return page_url

