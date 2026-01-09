# YouTube to Notion

Frictionless automation to save YouTube video insights to Notion. Share any video from your iPhone and get organized notes automatically.

## Quick Start

### 1. Set Up Notion

1. **Create Integration**: Go to [notion.so/my-integrations](https://www.notion.so/my-integrations) → New integration → Name it "YouTube Summary"
2. **Create Database**: New page → Add database → Table view with columns:
   - `title` (Title - default)
   - `URL` (URL type)
   - `Added` (Date type)  
3. **Connect**: Open database → `•••` → Connections → Add your integration
4. **Copy Database ID**: From URL `notion.so/workspace/{DATABASE_ID}?v=...`

### 2. Get API Keys

- **Gemini**: [aistudio.google.com/apikey](https://aistudio.google.com/apikey) (free)
- **Notion Token**: From your integration page

### 3. Deploy to Railway

1. Push to GitHub
2. Connect repo in [Railway](https://railway.app)
3. Add environment variables:
   ```
   GEMINI_API_KEY=your_key
   NOTION_TOKEN=your_token
   NOTION_DATABASE_ID=your_db_id
   ```
4. Deploy → Copy your app URL

### 4. Create iOS Shortcut

See [docs/ios-shortcut-guide.md](docs/ios-shortcut-guide.md) for step-by-step instructions.

## API

```bash
POST /summarize
Content-Type: application/json

{"url": "https://youtube.com/watch?v=..."}
```

Response:
```json
{
  "success": true,
  "title": "Video Title",
  "notionUrl": "https://notion.so/..."
}
```

## Local Development

```bash
cp .env.example .env
# Edit .env with your keys
npm install
npm run dev
```
