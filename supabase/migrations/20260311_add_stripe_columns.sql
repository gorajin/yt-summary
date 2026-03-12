-- Add Stripe customer and subscription tracking columns
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS stripe_customer_id TEXT;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS stripe_subscription_id TEXT;

-- Index for webhook lookups by Stripe customer ID
CREATE INDEX IF NOT EXISTS idx_users_stripe_customer_id
    ON public.users(stripe_customer_id) WHERE stripe_customer_id IS NOT NULL;
