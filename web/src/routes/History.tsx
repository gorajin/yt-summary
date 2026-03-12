import { useEffect, useState } from 'react'
import { getSummaryHistory } from '../services/api'
import type { SummaryItem } from '../services/api'
import SummaryCard from '../components/SummaryCard'

export default function History() {
  const [summaries, setSummaries] = useState<SummaryItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    getSummaryHistory()
      .then(setSummaries)
      .catch((err) => setError(err.message ?? 'Failed to load history'))
      .finally(() => setLoading(false))
  }, [])

  if (loading) {
    return (
      <div className="page-container">
        <div className="loading-section">
          <div className="spinner" />
          <p>Loading summaries...</p>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="page-container">
        <div className="error-banner">{error}</div>
      </div>
    )
  }

  return (
    <div className="page-container">
      <h2>Summary History</h2>
      {summaries.length === 0 ? (
        <div className="empty-state">
          <h3>No summaries yet</h3>
          <p>Summarize your first YouTube video to see it here.</p>
        </div>
      ) : (
        <div className="summary-list">
          {summaries.map((s) => (
            <SummaryCard key={s.id} summary={s} />
          ))}
        </div>
      )}
    </div>
  )
}
