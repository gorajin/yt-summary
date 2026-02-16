-- Knowledge Maps table
-- Stores a per-user knowledge map synthesized from all their summaries.
-- One row per user (UNIQUE constraint), updated on rebuild.

CREATE TABLE IF NOT EXISTS knowledge_maps (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES auth.users(id),
    map_json JSONB NOT NULL DEFAULT '{}',
    version INTEGER NOT NULL DEFAULT 1,
    summary_count INTEGER NOT NULL DEFAULT 0,
    notion_url TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id)
);

-- RLS policies
ALTER TABLE knowledge_maps ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can read own knowledge map"
    ON knowledge_maps FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Service role can manage knowledge maps"
    ON knowledge_maps FOR ALL
    USING (true)
    WITH CHECK (true);
