/**
 * YouTube to Notion API
 * Main Express server that orchestrates the automation
 */

import 'dotenv/config';
import express from 'express';
import { getTranscript } from './youtube.js';
import { summarizeTranscript } from './gemini.js';
import { createNotionPage } from './notion.js';

const app = express();
app.use(express.json());

// Health check endpoint
app.get('/', (req, res) => {
    res.json({
        status: 'ok',
        service: 'YouTube to Notion API',
        endpoints: {
            'POST /summarize': 'Submit a YouTube URL for summarization'
        }
    });
});

// Main summarization endpoint
app.post('/summarize', async (req, res) => {
    const startTime = Date.now();

    try {
        const { url } = req.body;

        if (!url) {
            return res.status(400).json({
                success: false,
                error: 'Missing required field: url'
            });
        }

        console.log(`[${new Date().toISOString()}] Processing: ${url}`);

        // Step 1: Extract transcript
        console.log('  → Fetching transcript...');
        const { transcript, videoId } = await getTranscript(url);
        console.log(`  → Got transcript (${transcript.length} chars)`);

        // Step 2: Summarize with Gemini
        console.log('  → Summarizing with Gemini...');
        const summary = await summarizeTranscript(transcript);
        console.log(`  → Generated summary: "${summary.title}"`);

        // Step 3: Create Notion page
        console.log('  → Creating Notion page...');
        const { pageUrl } = await createNotionPage({
            title: summary.title,
            url: `https://youtu.be/${videoId}`,
            oneLiner: summary.oneLiner,
            keyTakeaways: summary.keyTakeaways,
            insights: summary.insights,
        });

        const duration = Date.now() - startTime;
        console.log(`  ✓ Complete in ${duration}ms → ${pageUrl}`);

        res.json({
            success: true,
            title: summary.title,
            notionUrl: pageUrl,
            processingTime: `${duration}ms`,
        });

    } catch (error) {
        console.error(`  ✗ Error: ${error.message}`);

        res.status(500).json({
            success: false,
            error: error.message,
        });
    }
});

// Start server
const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
    console.log(`🚀 YouTube to Notion API running on port ${PORT}`);
    console.log(`   Health check: http://localhost:${PORT}/`);
    console.log(`   Summarize:    POST http://localhost:${PORT}/summarize`);
});
