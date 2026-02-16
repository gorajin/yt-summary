#!/usr/bin/env python3
"""
Diagnostic script to check and fix user's Notion database_id in Supabase.

Usage:
    python fix_user_notion.py <user_id>

Example:
    python fix_user_notion.py bd37a28a-d6e4-4d77-a85a-e31789c9024e
"""

import os
import sys
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("ERROR: SUPABASE_URL and SUPABASE_KEY must be set in .env")
    exit(1)

# Accept user ID as CLI argument
if len(sys.argv) < 2:
    print("Usage: python fix_user_notion.py <user_id>")
    print("Example: python fix_user_notion.py bd37a28a-d6e4-4d77-a85a-e31789c9024e")
    exit(1)

USER_ID = sys.argv[1]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

print(f"Checking user: {USER_ID}")
print("-" * 50)

# Fetch current user record
result = supabase.table("users").select("*").eq("id", USER_ID).execute()

if not result.data:
    print("ERROR: User not found!")
    exit(1)

user = result.data[0]
print(f"Email: {user.get('email')}")
print(f"Subscription: {user.get('subscription_tier')}")
print(f"Notion Token: {'SET' if user.get('notion_access_token') else 'NULL'}")
print(f"Notion Database ID: {user.get('notion_database_id') or 'NULL'}")
print(f"Notion Workspace: {user.get('notion_workspace') or 'NULL'}")

if user.get('notion_access_token') and not user.get('notion_database_id'):
    print("\n⚠️  ISSUE FOUND: Has token but no database_id!")
    print("\nTo fix this, the user needs to:")
    print("1. Go to Notion and share a database with the WatchLater integration")
    print("2. Reconnect Notion in the app after backend is redeployed")
    
    # Try to find a database using the user's token
    print("\n" + "-" * 50)
    print("Attempting to find a database using user's token...")
    
    try:
        from notion_client import Client as NotionClient
        notion = NotionClient(auth=user['notion_access_token'])
        search_results = notion.search(filter={"property": "object", "value": "database"}).get("results", [])
        
        print(f"Found {len(search_results)} databases:")
        for i, db in enumerate(search_results):
            title = db.get("title", [{}])[0].get("plain_text", "Untitled")
            print(f"  {i+1}. {title} (ID: {db['id']})")
        
        if search_results:
            first_db = search_results[0]
            first_db_id = first_db["id"]
            first_db_title = first_db.get("title", [{}])[0].get("plain_text", "Untitled")
            
            print(f"\n🔧 Fixing: Setting database_id to first database: {first_db_title}")
            
            supabase.table("users").update({
                "notion_database_id": first_db_id
            }).eq("id", USER_ID).execute()
            
            print(f"✅ FIXED! database_id set to: {first_db_id}")
            print("\nPlease refresh the app (pull down to refresh or restart)")
        else:
            print("\n🔧 No databases found - creating 'YouTube Summaries' database...")
            
            # Search for pages to use as parent
            page_results = notion.search(filter={"property": "object", "value": "page"}).get("results", [])
            
            if page_results:
                parent_page_id = page_results[0]["id"]
                print(f"Using page {parent_page_id} as parent")
                
                # Create database with proper schema
                new_db = notion.databases.create(
                    parent={"type": "page_id", "page_id": parent_page_id},
                    title=[{"type": "text", "text": {"content": "YouTube Summaries"}}],
                    properties={
                        "Title": {"title": {}},
                        "URL": {"url": {}},
                        "Type": {
                            "select": {
                                "options": [
                                    {"name": "Lecture", "color": "blue"},
                                    {"name": "Tutorial", "color": "green"},
                                    {"name": "Interview", "color": "purple"},
                                    {"name": "Documentary", "color": "orange"},
                                    {"name": "General", "color": "gray"}
                                ]
                            }
                        },
                        "Date Added": {"date": {}}
                    }
                )
                database_id = new_db["id"]
                print(f"✓ Created database: YouTube Summaries ({database_id})")
                
                # Update Supabase
                supabase.table("users").update({
                    "notion_database_id": database_id
                }).eq("id", USER_ID).execute()
                
                print(f"✅ FIXED! database_id set to: {database_id}")
                print("\nPlease refresh the app (pull down to refresh or restart)")
            else:
                print("\n❌ No pages found! User needs to share at least one page with the WatchLater integration in Notion.")
            
    except Exception as e:
        print(f"Error accessing Notion: {e}")
        
else:
    print("\n✅ User record looks OK")
