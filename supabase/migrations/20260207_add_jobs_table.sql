-- Migration: Add jobs table for persistent async job tracking
-- Previously jobs were stored in-memory and lost on Railway restarts

CREATE TABLE IF NOT EXISTS public.jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES public.users(id) ON DELETE CASCADE,
    youtube_url TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'complete', 'failed')),
    progress INT DEFAULT 0 CHECK (progress >= 0 AND progress <= 100),
    stage TEXT DEFAULT 'queued',
    result JSONB DEFAULT NULL,
    error TEXT DEFAULT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_jobs_user_id ON public.jobs(user_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON public.jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON public.jobs(created_at);

-- RLS
ALTER TABLE public.jobs ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own jobs" ON public.jobs
    FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Service role full access jobs" ON public.jobs
    FOR ALL USING (auth.role() = 'service_role');

-- Grant permissions
GRANT ALL ON public.jobs TO service_role;
GRANT SELECT ON public.jobs TO authenticated;

-- Auto-cleanup function: removes jobs older than 24 hours
CREATE OR REPLACE FUNCTION cleanup_old_jobs(max_age_hours INT DEFAULT 24)
RETURNS INT AS $$
DECLARE
    deleted_count INT;
BEGIN
    DELETE FROM public.jobs 
    WHERE created_at < NOW() - (max_age_hours || ' hours')::INTERVAL;
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
