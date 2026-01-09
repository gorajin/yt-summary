/**
 * Gemini AI Summarization
 * Uses Gemini 2.0 Flash to extract key insights from transcripts
 */

import { GoogleGenerativeAI } from '@google/generative-ai';

const genAI = new GoogleGenerativeAI(process.env.GEMINI_API_KEY);

const SUMMARIZATION_PROMPT = `You are an expert at extracting valuable insights from video content.

Analyze the following YouTube video transcript and provide a structured summary.

TRANSCRIPT:
{transcript}

---

Respond in the following JSON format ONLY (no markdown, no code blocks, just raw JSON):
{
  "title": "A clear, descriptive title for this video based on content",
  "oneLiner": "A single sentence capturing the main point",
  "keyTakeaways": [
    "First key takeaway",
    "Second key takeaway", 
    "Third key takeaway"
  ],
  "insights": [
    "Notable insight or interesting idea #1",
    "Notable insight or interesting idea #2"
  ]
}

Guidelines:
- Title should be concise but descriptive (not clickbait)
- Key takeaways should be actionable or memorable points (3-5 items)
- Insights should capture unique perspectives or "aha moments" (2-4 items)
- Write in clear, professional language
- If the transcript seems incomplete or unclear, do your best with available content`;

/**
 * Summarize a transcript using Gemini 2.0 Flash
 */
export async function summarizeTranscript(transcript) {
    if (!process.env.GEMINI_API_KEY) {
        throw new Error('GEMINI_API_KEY environment variable is not set');
    }

    const model = genAI.getGenerativeModel({ model: 'gemini-2.0-flash' });

    const prompt = SUMMARIZATION_PROMPT.replace('{transcript}', transcript);

    try {
        const result = await model.generateContent(prompt);
        const response = result.response;
        const text = response.text();

        // Parse JSON response
        const cleanedText = text.replace(/```json\n?|\n?```/g, '').trim();
        const summary = JSON.parse(cleanedText);

        return {
            title: summary.title || 'Untitled Video',
            oneLiner: summary.oneLiner || '',
            keyTakeaways: summary.keyTakeaways || [],
            insights: summary.insights || [],
        };
    } catch (error) {
        if (error instanceof SyntaxError) {
            throw new Error('Failed to parse AI response - invalid JSON');
        }
        throw error;
    }
}
