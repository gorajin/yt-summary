-- Migration to add tracking columns for user preferences
ALTER TABLE public.summaries 
ADD COLUMN IF NOT EXISTS summary_format text,
ADD COLUMN IF NOT EXISTS language text;
