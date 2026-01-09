/**
 * Notion Integration
 * Creates pages in Notion database with video summaries
 */

import { Client } from '@notionhq/client';

let notion = null;

function getNotionClient() {
    if (!notion) {
        if (!process.env.NOTION_TOKEN) {
            throw new Error('NOTION_TOKEN environment variable is not set');
        }
        notion = new Client({ auth: process.env.NOTION_TOKEN });
    }
    return notion;
}

/**
 * Create a new page in Notion with the video summary
 */
export async function createNotionPage({ title, url, oneLiner, keyTakeaways, insights }) {
    const client = getNotionClient();

    if (!process.env.NOTION_DATABASE_ID) {
        throw new Error('NOTION_DATABASE_ID environment variable is not set');
    }

    const databaseId = process.env.NOTION_DATABASE_ID;

    // Build page content blocks
    const children = [
        // One-liner summary callout
        {
            object: 'block',
            type: 'callout',
            callout: {
                rich_text: [{ type: 'text', text: { content: oneLiner } }],
                icon: { emoji: '💡' },
                color: 'blue_background',
            },
        },
        // Divider
        { object: 'block', type: 'divider', divider: {} },
        // Key Takeaways header
        {
            object: 'block',
            type: 'heading_2',
            heading_2: {
                rich_text: [{ type: 'text', text: { content: '🎯 Key Takeaways' } }],
            },
        },
        // Key takeaways as bullet list
        ...keyTakeaways.map(takeaway => ({
            object: 'block',
            type: 'bulleted_list_item',
            bulleted_list_item: {
                rich_text: [{ type: 'text', text: { content: takeaway } }],
            },
        })),
        // Divider
        { object: 'block', type: 'divider', divider: {} },
        // Insights header
        {
            object: 'block',
            type: 'heading_2',
            heading_2: {
                rich_text: [{ type: 'text', text: { content: '✨ Notable Insights' } }],
            },
        },
        // Insights as bullet list
        ...insights.map(insight => ({
            object: 'block',
            type: 'bulleted_list_item',
            bulleted_list_item: {
                rich_text: [{ type: 'text', text: { content: insight } }],
            },
        })),
    ];

    // Create the page
    const response = await client.pages.create({
        parent: { database_id: databaseId },
        properties: {
            // Title property (required for database pages)
            title: {
                title: [{ text: { content: title } }],
            },
            // URL property
            URL: {
                url: url,
            },
            // Date added
            Added: {
                date: { start: new Date().toISOString().split('T')[0] },
            },
        },
        children: children,
    });

    return {
        pageId: response.id,
        pageUrl: response.url,
    };
}
