import { useState, useEffect, useCallback } from 'react'
import { getProfile, submitSummarize, getJobStatus } from '../services/api'
import type { UserProfile } from '../services/api'

function extractVideoId(url: string): string | null {
  const patterns = [
    /(?:youtube\.com\/watch\?v=)([a-zA-Z0-9_-]{11})/,
    /(?:youtu\.be\/)([a-zA-Z0-9_-]{11})/,
    /(?:youtube\.com\/embed\/)([a-zA-Z0-9_-]{11})/,
    /(?:youtube\.com\/shorts\/)([a-zA-Z0-9_-]{11})/,
  ]
  for (const pattern of patterns) {
    const match = url.match(pattern)
    if (match) return match[1]
  }
  return null
}

export default function Home() {
  const [url, setUrl] = useState('')
  const [format, setFormat] = useState('detailed')
  const [language, setLanguage] = useState('en')
  const [profile, setProfile] = useState<UserProfile | null>(null)
  const [processing, setProcessing] = useState(false)
  const [stage, setStage] = useState('')
  const [progress, setProgress] = useState(0)
  const [result, setResult] = useState<{ success: boolean; message: string } | null>(null)

  useEffect(() => {
    getProfile()
      .then(setProfile)
      .catch(() => {})
  }, [])

  const videoId = extractVideoId(url)
  const thumbnailUrl = videoId
    ? `https://img.youtube.com/vi/${videoId}/mqdefault.jpg`
    : null

  const pollJob = useCallback(async (jobId: string) => {
    for (let i = 0; i < 80; i++) {
      try {
        const status = await getJobStatus(jobId)
        setStage(status.stage ?? 'Processing...')
        setProgress(status.progress ?? 0)

        if (status.status === 'complete') {
          setResult({
            success: true,
            message: `Saved: ${status.result?.title ?? 'Summary'}`,
          })
          setProcessing(false)
          // Refresh remaining count
          getProfile().then(setProfile).catch(() => {})
          return
        }
        if (status.status === 'failed') {
          setResult({
            success: false,
            message: status.error ?? 'Processing failed',
          })
          setProcessing(false)
          return
        }
      } catch {
        // Continue polling on network errors
      }
      await new Promise((r) => setTimeout(r, 3000))
    }
    setResult({ success: false, message: 'Processing timed out' })
    setProcessing(false)
  }, [])

  async function handleSummarize() {
    if (!url.trim() || processing) return
    setProcessing(true)
    setResult(null)
    setStage('Submitting...')
    setProgress(0)

    try {
      const job = await submitSummarize(url, format, language)
      await pollJob(job.job_id)
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : 'Failed to submit'
      setResult({ success: false, message })
      setProcessing(false)
    }
  }

  return (
    <div className="page-container">
      <div className="home-card">
        <h2>Summarize a YouTube Video</h2>

        {/* URL Input */}
        <div className="input-group">
          <input
            type="url"
            placeholder="Paste YouTube URL..."
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            disabled={processing}
            className="url-input"
          />
        </div>

        {/* Thumbnail preview */}
        {thumbnailUrl && (
          <div className="thumbnail-preview">
            <img src={thumbnailUrl} alt="Video thumbnail" />
          </div>
        )}

        {/* Options */}
        <div className="options-row">
          <select value={format} onChange={(e) => setFormat(e.target.value)}>
            <option value="detailed">Detailed</option>
            <option value="short">Short</option>
            <option value="actionable">Actionable</option>
          </select>

          <select value={language} onChange={(e) => setLanguage(e.target.value)}>
            <option value="en">English</option>
            <option value="es">Spanish</option>
            <option value="fr">French</option>
            <option value="de">German</option>
            <option value="ko">Korean</option>
            <option value="ja">Japanese</option>
            <option value="zh">Chinese</option>
          </select>
        </div>

        {/* Submit button */}
        <button
          className="btn btn-primary btn-lg"
          onClick={handleSummarize}
          disabled={!url.trim() || processing}
        >
          {processing ? (
            <div className="progress-content">
              <span>{stage}</span>
              <div className="progress-bar">
                <div
                  className="progress-fill"
                  style={{ width: `${Math.min(progress, 100)}%` }}
                />
              </div>
            </div>
          ) : (
            'Summarize & Save'
          )}
        </button>

        {/* Result message */}
        {result && (
          <div className={`result-banner ${result.success ? 'success' : 'error'}`}>
            {result.message}
          </div>
        )}

        {/* Remaining count */}
        {profile && (
          <p className="remaining-text">
            {profile.summaries_remaining < 0
              ? 'Unlimited summaries'
              : `${profile.summaries_remaining} summaries remaining this month`}
          </p>
        )}
      </div>
    </div>
  )
}
