-- Add share_token column to knowledge_maps for public sharing
-- A unique token that enables public (no-auth) access to a knowledge map

ALTER TABLE public.knowledge_maps
    ADD COLUMN IF NOT EXISTS share_token TEXT UNIQUE;

-- Index for fast lookups by share_token
CREATE INDEX IF NOT EXISTS idx_knowledge_maps_share_token
    ON public.knowledge_maps(share_token)
    WHERE share_token IS NOT NULL;
