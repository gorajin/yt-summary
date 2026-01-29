-- Add missing notion_url column to summaries table
-- This is a non-breaking change - existing rows will have NULL

ALTER TABLE summaries ADD COLUMN IF NOT EXISTS notion_url TEXT;

-- Optional: Add an index if we later want to query by notion_url
-- CREATE INDEX IF NOT EXISTS idx_summaries_notion_url ON summaries(notion_url);
