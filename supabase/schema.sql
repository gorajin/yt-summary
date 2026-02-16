-- Supabase SQL Schema for YouTube Summary App
-- Run this in the Supabase SQL Editor

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Users table (extends Supabase auth.users)
CREATE TABLE IF NOT EXISTS public.users (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email TEXT,
    notion_access_token TEXT,
    notion_database_id TEXT,
    notion_workspace TEXT,
    subscription_tier TEXT DEFAULT 'free' CHECK (subscription_tier IN ('free', 'pro', 'lifetime')),
    summaries_this_month INT DEFAULT 0,
    summaries_reset_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    original_transaction_id TEXT,                        -- Apple original transaction ID
    subscription_product_id TEXT,                        -- e.g. com.watchlater.app.pro.monthly
    subscription_expires_at TIMESTAMP WITH TIME ZONE,    -- When the current subscription period ends
    email_digest_enabled BOOLEAN DEFAULT true,           -- Whether to send daily digest emails
    email_digest_time TEXT DEFAULT '20:00',               -- User's preferred digest time (HH:MM)
    timezone TEXT DEFAULT 'UTC',                          -- User's timezone for digest scheduling
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Migration for existing installations (subscription tracking):
-- ALTER TABLE public.users ADD COLUMN IF NOT EXISTS original_transaction_id TEXT;
-- ALTER TABLE public.users ADD COLUMN IF NOT EXISTS subscription_product_id TEXT;
-- ALTER TABLE public.users ADD COLUMN IF NOT EXISTS subscription_expires_at TIMESTAMP WITH TIME ZONE;
-- ALTER TABLE public.users ADD COLUMN IF NOT EXISTS email_digest_enabled BOOLEAN DEFAULT true;
-- ALTER TABLE public.users ADD COLUMN IF NOT EXISTS email_digest_time TEXT DEFAULT '20:00';
-- ALTER TABLE public.users ADD COLUMN IF NOT EXISTS timezone TEXT DEFAULT 'UTC';

-- Summaries log table
CREATE TABLE IF NOT EXISTS public.summaries (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES public.users(id) ON DELETE CASCADE,
    youtube_url TEXT NOT NULL,
    video_id TEXT,                                       -- YouTube video ID for deep links
    title TEXT,
    overview TEXT,                                       -- One-liner summary for list previews
    content_type TEXT,                                   -- lecture, interview, tutorial, etc.
    summary_json JSONB,                                  -- Full LectureNotes JSON for in-app reading
    notion_url TEXT,                                     -- Notion page URL (optional)
    source_type TEXT DEFAULT 'youtube',                  -- youtube, article, pdf, podcast
    source_url TEXT,                                     -- Original source URL (for non-YouTube)
    deleted_at TIMESTAMP WITH TIME ZONE DEFAULT NULL,    -- Soft delete timestamp
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Migration for existing installations:
-- ALTER TABLE public.summaries ADD COLUMN IF NOT EXISTS notion_url TEXT;
-- ALTER TABLE public.summaries ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP WITH TIME ZONE DEFAULT NULL;
-- ALTER TABLE public.summaries ADD COLUMN IF NOT EXISTS video_id TEXT;
-- ALTER TABLE public.summaries ADD COLUMN IF NOT EXISTS overview TEXT;
-- ALTER TABLE public.summaries ADD COLUMN IF NOT EXISTS content_type TEXT;
-- ALTER TABLE public.summaries ADD COLUMN IF NOT EXISTS summary_json JSONB;
-- ALTER TABLE public.summaries ADD COLUMN IF NOT EXISTS source_type TEXT DEFAULT 'youtube';
-- ALTER TABLE public.summaries ADD COLUMN IF NOT EXISTS source_url TEXT;

-- Function to increment summary count
CREATE OR REPLACE FUNCTION increment_summaries(p_user_id UUID)
RETURNS VOID AS $$
BEGIN
    UPDATE public.users 
    SET 
        summaries_this_month = summaries_this_month + 1,
        updated_at = NOW()
    WHERE id = p_user_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to reset monthly summaries (run via cron)
CREATE OR REPLACE FUNCTION reset_monthly_summaries()
RETURNS VOID AS $$
BEGIN
    UPDATE public.users 
    SET 
        summaries_this_month = 0,
        summaries_reset_at = NOW()
    WHERE subscription_tier = 'free';
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Row Level Security (RLS)
ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.summaries ENABLE ROW LEVEL SECURITY;

-- Users can only read/update their own data
CREATE POLICY "Users can view own profile" ON public.users
    FOR SELECT USING (auth.uid() = id);

CREATE POLICY "Users can update own profile" ON public.users
    FOR UPDATE USING (auth.uid() = id);

-- Summaries policy
CREATE POLICY "Users can view own summaries" ON public.summaries
    FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own summaries" ON public.summaries
    FOR INSERT WITH CHECK (auth.uid() = user_id);

-- Service role bypass (for backend API)
CREATE POLICY "Service role full access users" ON public.users
    FOR ALL USING (auth.role() = 'service_role');

CREATE POLICY "Service role full access summaries" ON public.summaries
    FOR ALL USING (auth.role() = 'service_role');

-- Indexes
CREATE INDEX IF NOT EXISTS idx_users_email ON public.users(email);
CREATE INDEX IF NOT EXISTS idx_summaries_user_id ON public.summaries(user_id);
CREATE INDEX IF NOT EXISTS idx_summaries_created_at ON public.summaries(created_at);

-- Grant permissions
GRANT ALL ON public.users TO service_role;
GRANT ALL ON public.summaries TO service_role;
GRANT SELECT, UPDATE ON public.users TO authenticated;
GRANT SELECT, INSERT ON public.summaries TO authenticated;
