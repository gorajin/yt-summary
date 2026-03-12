import { useState } from 'react'
import { exportSummary } from '../services/api'
import type { SummaryItem } from '../services/api'

interface SummaryCardProps {
  summary: SummaryItem
}

export default function SummaryCard({ summary }: SummaryCardProps) {
  const [exporting, setExporting] = useState(false)

  const thumbnailUrl = summary.video_id
    ? `https://img.youtube.com/vi/${summary.video_id}/mqdefault.jpg`
    : null

  async function handleExport(format: 'markdown' | 'html' | 'text') {
    setExporting(true)
    try {
      const data = await exportSummary(summary.id, format)
      const blob = new Blob([data.content], { type: data.content_type })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = data.filename
      a.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      console.error('Export failed:', err)
    }
    setExporting(false)
  }

  const dateStr = summary.created_at
    ? new Date(summary.created_at).toLocaleDateString()
    : ''

  return (
    <div className="summary-card">
      <div className="summary-card-body">
        {thumbnailUrl && (
          <a
            href={summary.youtube_url}
            target="_blank"
            rel="noopener noreferrer"
            className="summary-thumbnail"
          >
            <img src={thumbnailUrl} alt={summary.title} />
          </a>
        )}
        <div className="summary-info">
          <h3>
            <a href={summary.youtube_url} target="_blank" rel="noopener noreferrer">
              {summary.title}
            </a>
          </h3>
          {summary.overview && <p className="summary-overview">{summary.overview}</p>}
          <div className="summary-meta">
            {summary.content_type && (
              <span className="badge">{summary.content_type}</span>
            )}
            {summary.summary_format && (
              <span className="badge badge-outline">{summary.summary_format}</span>
            )}
            <span className="date">{dateStr}</span>
          </div>
        </div>
      </div>

      <div className="summary-actions">
        {summary.notion_url && (
          <a
            href={summary.notion_url}
            target="_blank"
            rel="noopener noreferrer"
            className="btn btn-sm"
          >
            Open in Notion
          </a>
        )}
        <button
          className="btn btn-sm btn-outline"
          onClick={() => handleExport('markdown')}
          disabled={exporting}
        >
          {exporting ? '...' : 'Export MD'}
        </button>
        <button
          className="btn btn-sm btn-outline"
          onClick={() => handleExport('html')}
          disabled={exporting}
        >
          Export HTML
        </button>
      </div>
    </div>
  )
}
