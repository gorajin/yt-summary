import { useEffect, useState, useCallback } from 'react'
import { getKnowledgeMap, buildKnowledgeMap, getJobStatus } from '../services/api'
import type { TopicData, ConnectionData } from '../services/api'
import TopicGraph from '../components/TopicGraph'

export default function KnowledgeMap() {
  const [topics, setTopics] = useState<TopicData[]>([])
  const [connections, setConnections] = useState<ConnectionData[]>([])
  const [loading, setLoading] = useState(true)
  const [building, setBuilding] = useState(false)
  const [buildStage, setBuildStage] = useState('')
  const [selectedTopic, setSelectedTopic] = useState<TopicData | null>(null)
  const [isStale, setIsStale] = useState(false)
  const [viewMode, setViewMode] = useState<'graph' | 'list'>('graph')

  const loadMap = useCallback(async () => {
    setLoading(true)
    try {
      const data = await getKnowledgeMap()
      setTopics(data.knowledgeMap?.topics ?? [])
      setConnections(data.knowledgeMap?.connections ?? [])
      setIsStale(data.isStale ?? false)
    } catch {
      // Map may not exist yet
    }
    setLoading(false)
  }, [])

  useEffect(() => {
    loadMap()
  }, [loadMap])

  async function handleBuild() {
    setBuilding(true)
    setBuildStage('Starting build...')
    try {
      const { jobId } = await buildKnowledgeMap()
      // Poll for completion
      for (let i = 0; i < 120; i++) {
        const status = await getJobStatus(jobId)
        setBuildStage(status.stage ?? 'Processing...')
        if (status.status === 'complete') {
          await loadMap()
          break
        }
        if (status.status === 'failed') {
          setBuildStage(`Failed: ${status.error}`)
          break
        }
        await new Promise((r) => setTimeout(r, 3000))
      }
    } catch (err: unknown) {
      setBuildStage(err instanceof Error ? err.message : 'Build failed')
    }
    setBuilding(false)
  }

  if (loading) {
    return (
      <div className="page-container">
        <div className="loading-section">
          <div className="spinner" />
          <p>Loading knowledge map...</p>
        </div>
      </div>
    )
  }

  if (topics.length === 0 && !building) {
    return (
      <div className="page-container">
        <div className="empty-state">
          <h2>Build Your Knowledge Map</h2>
          <p>
            Synthesize all your video summaries into an organized topic graph
            with connections.
          </p>
          <button className="btn btn-primary" onClick={handleBuild} disabled={building}>
            {building ? buildStage : 'Build Knowledge Map'}
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="page-container knowledge-map-page">
      <div className="km-header">
        <h2>Knowledge Map</h2>
        <div className="km-actions">
          {isStale && (
            <span className="badge badge-warning">New summaries available</span>
          )}
          <button
            className={`btn btn-sm ${viewMode === 'graph' ? 'btn-primary' : 'btn-outline'}`}
            onClick={() => setViewMode('graph')}
          >
            Graph
          </button>
          <button
            className={`btn btn-sm ${viewMode === 'list' ? 'btn-primary' : 'btn-outline'}`}
            onClick={() => setViewMode('list')}
          >
            List
          </button>
          <button
            className="btn btn-sm btn-outline"
            onClick={handleBuild}
            disabled={building}
          >
            {building ? 'Building...' : 'Rebuild'}
          </button>
        </div>
      </div>

      {building && (
        <div className="build-overlay">
          <div className="spinner" />
          <p>{buildStage}</p>
        </div>
      )}

      {viewMode === 'graph' ? (
        <TopicGraph
          topics={topics.slice(0, 25)}
          connections={connections}
          onSelectTopic={setSelectedTopic}
        />
      ) : (
        <div className="topic-list">
          {topics
            .sort((a, b) => (b.importance ?? 5) - (a.importance ?? 5))
            .map((topic) => (
              <div
                key={topic.name}
                className="topic-card"
                onClick={() => setSelectedTopic(topic)}
              >
                <div className="topic-card-header">
                  <h3>{topic.name}</h3>
                  <div className="importance-dots">
                    {Array.from({ length: Math.min(topic.importance ?? 5, 10) }).map(
                      (_, i) => (
                        <span
                          key={i}
                          className={`dot ${
                            (topic.importance ?? 5) >= 8
                              ? 'high'
                              : (topic.importance ?? 5) >= 5
                              ? 'medium'
                              : 'low'
                          }`}
                        />
                      )
                    )}
                  </div>
                </div>
                <p>{topic.description}</p>
                <div className="topic-meta">
                  <span>{topic.videoIds?.length ?? 0} videos</span>
                  <span>{topic.facts?.length ?? 0} facts</span>
                </div>
              </div>
            ))}
        </div>
      )}

      {/* Topic Detail Modal */}
      {selectedTopic && (
        <div className="modal-overlay" onClick={() => setSelectedTopic(null)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>{selectedTopic.name}</h2>
              <button className="btn-close" onClick={() => setSelectedTopic(null)}>
                &times;
              </button>
            </div>
            <p className="topic-description">{selectedTopic.description}</p>

            {selectedTopic.facts && selectedTopic.facts.length > 0 && (
              <div className="topic-section">
                <h3>Key Facts</h3>
                <ul>
                  {selectedTopic.facts.map((fact, i) => (
                    <li key={i}>
                      {fact.fact}
                      {fact.sourceTitle && (
                        <span className="fact-source"> — {fact.sourceTitle}</span>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {selectedTopic.relatedTopics && selectedTopic.relatedTopics.length > 0 && (
              <div className="topic-section">
                <h3>Related Topics</h3>
                <div className="tag-list">
                  {selectedTopic.relatedTopics.map((name) => (
                    <span key={name} className="tag">
                      {name}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
