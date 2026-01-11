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
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Summaries log table
CREATE TABLE IF NOT EXISTS public.summaries (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES public.users(id) ON DELETE CASCADE,
    youtube_url TEXT NOT NULL,
    title TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

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
