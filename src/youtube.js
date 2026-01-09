/**
 * YouTube Transcript Extractor
 * Uses direct YouTube caption fetching approach
 */

/**
 * Extract video ID from various YouTube URL formats
 */
export function extractVideoId(url) {
  const patterns = [
    /(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/shorts\/)([a-zA-Z0-9_-]{11})/,
    /(?:youtube\.com\/embed\/)([a-zA-Z0-9_-]{11})/,
    /(?:youtube\.com\/v\/)([a-zA-Z0-9_-]{11})/,
  ];

  for (const pattern of patterns) {
    const match = url.match(pattern);
    if (match) return match[1];
  }

  if (/^[a-zA-Z0-9_-]{11}$/.test(url)) {
    return url;
  }

  return null;
}

/**
 * Fetch transcript using YouTube's timedtext API
 */
export async function getTranscript(url) {
  const videoId = extractVideoId(url);

  if (!videoId) {
    throw new Error('Invalid YouTube URL - could not extract video ID');
  }

  try {
    // First, fetch the video page to extract caption track info
    const videoPageUrl = `https://www.youtube.com/watch?v=${videoId}`;
    const response = await fetch(videoPageUrl, {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
      },
    });

    const html = await response.text();

    // Extract video title
    const titleMatch = html.match(/<title>([^<]*)<\/title>/);
    let videoTitle = titleMatch ? titleMatch[1].replace(' - YouTube', '').trim() : 'Untitled Video';

    // Look for captions data in the page
    const captionMatch = html.match(/"captions":\s*(\{[^}]+playerCaptionsTracklistRenderer[^}]+\})/);

    if (!captionMatch) {
      // Try alternative pattern for caption URLs
      const timedTextMatch = html.match(/https:\/\/www\.youtube\.com\/api\/timedtext[^"]+/g);

      if (timedTextMatch && timedTextMatch.length > 0) {
        // Use the first caption track found
        let captionUrl = timedTextMatch[0].replace(/\\u0026/g, '&');

        // Fetch the captions
        const captionResponse = await fetch(captionUrl);
        const captionData = await captionResponse.text();

        // Parse XML captions
        const textMatches = captionData.match(/<text[^>]*>([^<]*)<\/text>/g);
        if (textMatches) {
          const transcript = textMatches
            .map(t => t.replace(/<[^>]+>/g, '').replace(/&amp;/g, '&').replace(/&#39;/g, "'").replace(/&quot;/g, '"'))
            .join(' ')
            .replace(/\s+/g, ' ')
            .trim();

          return {
            videoId,
            transcript,
            title: videoTitle,
            segmentCount: textMatches.length,
          };
        }
      }

      throw new Error('This video does not have captions/transcripts available');
    }

    // Extract baseUrl from captions data
    const baseUrlMatch = html.match(/"baseUrl"\s*:\s*"(https:\/\/www\.youtube\.com\/api\/timedtext[^"]+)"/);

    if (!baseUrlMatch) {
      throw new Error('Could not find caption URL');
    }

    let captionUrl = baseUrlMatch[1].replace(/\\u0026/g, '&');

    // Fetch the captions
    const captionResponse = await fetch(captionUrl);
    const captionData = await captionResponse.text();

    // Parse JSON3 format if available, otherwise XML
    if (captionData.startsWith('{')) {
      const json = JSON.parse(captionData);
      if (json.events) {
        const transcript = json.events
          .filter(e => e.segs)
          .map(e => e.segs.map(s => s.utf8).join(''))
          .join(' ')
          .replace(/\s+/g, ' ')
          .trim();

        return {
          videoId,
          transcript,
          title: videoTitle,
          segmentCount: json.events.length,
        };
      }
    }

    // Parse XML captions
    const textMatches = captionData.match(/<text[^>]*>([^<]*)<\/text>/g);
    if (textMatches) {
      const transcript = textMatches
        .map(t => t.replace(/<[^>]+>/g, '').replace(/&amp;/g, '&').replace(/&#39;/g, "'").replace(/&quot;/g, '"'))
        .join(' ')
        .replace(/\s+/g, ' ')
        .trim();

      return {
        videoId,
        transcript,
        title: videoTitle,
        segmentCount: textMatches.length,
      };
    }

    throw new Error('Could not parse caption data');

  } catch (error) {
    if (error.message.includes('transcript') || error.message.includes('caption')) {
      throw error;
    }
    console.error('Transcript Error:', error.message);
    throw new Error(`Failed to fetch transcript: ${error.message}`);
  }
}
