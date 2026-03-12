import { useState } from 'react'
import { createStripeCheckout } from '../services/api'
import type { Session } from '@supabase/supabase-js'
import { signInWithGoogle } from '../services/supabase'

interface PricingProps {
  session: Session | null
}

const MONTHLY_PRICE_ID = import.meta.env.VITE_STRIPE_PRO_MONTHLY_PRICE || ''
const YEARLY_PRICE_ID = import.meta.env.VITE_STRIPE_PRO_YEARLY_PRICE || ''

export default function Pricing({ session }: PricingProps) {
  const [loadingMonthly, setLoadingMonthly] = useState(false)
  const [loadingYearly, setLoadingYearly] = useState(false)
  const [error, setError] = useState('')

  async function handleCheckout(priceId: string, isYearly: boolean) {
    if (!session) {
      signInWithGoogle()
      return
    }
    const setter = isYearly ? setLoadingYearly : setLoadingMonthly
    setter(true)
    setError('')
    try {
      const { url } = await createStripeCheckout(priceId)
      window.location.href = url
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Checkout failed')
      setter(false)
    }
  }

  return (
    <div className="page-container pricing-page">
      <h1>Upgrade to Pro</h1>
      <p className="pricing-subtitle">
        Unlimited summaries, batch processing, and priority support.
        <br />
        Save more by subscribing on the web (no App Store fees).
      </p>

      {error && <div className="error-banner">{error}</div>}

      <div className="pricing-grid">
        {/* Monthly */}
        <div className="pricing-card">
          <h3>Monthly</h3>
          <div className="price">
            <span className="amount">$4.99</span>
            <span className="period">/month</span>
          </div>
          <ul className="features">
            <li>Unlimited summaries</li>
            <li>Batch/playlist processing</li>
            <li>All export formats</li>
            <li>Knowledge map</li>
            <li>Priority processing</li>
          </ul>
          <button
            className="btn btn-primary btn-lg"
            onClick={() => handleCheckout(MONTHLY_PRICE_ID, false)}
            disabled={loadingMonthly}
          >
            {loadingMonthly ? 'Redirecting...' : session ? 'Subscribe Monthly' : 'Sign in to Subscribe'}
          </button>
        </div>

        {/* Yearly */}
        <div className="pricing-card featured">
          <div className="pricing-badge">Save 33%</div>
          <h3>Yearly</h3>
          <div className="price">
            <span className="amount">$39.99</span>
            <span className="period">/year</span>
          </div>
          <ul className="features">
            <li>Everything in Monthly</li>
            <li>2 months free</li>
            <li>Early access to new features</li>
            <li>Knowledge map sharing</li>
            <li>Priority support</li>
          </ul>
          <button
            className="btn btn-primary btn-lg"
            onClick={() => handleCheckout(YEARLY_PRICE_ID, true)}
            disabled={loadingYearly}
          >
            {loadingYearly ? 'Redirecting...' : session ? 'Subscribe Yearly' : 'Sign in to Subscribe'}
          </button>
        </div>
      </div>

      {/* Free tier info */}
      <div className="free-tier-info">
        <h3>Free Plan</h3>
        <p>10 summaries/month. Perfect for trying out WatchLater.</p>
      </div>
    </div>
  )
}
