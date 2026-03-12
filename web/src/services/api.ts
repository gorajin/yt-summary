import axios from 'axios'
import { getAccessToken } from './supabase'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'https://watchlater.up.railway.app'

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
})

// Attach Bearer token to every request
api.interceptors.request.use(async (config) => {
  const token = await getAccessToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// ============ Types ============

export interface UserProfile {
  id: string
  email: string
  notion_connected: boolean
  subscription_tier: string
  summaries_this_month: number
  summaries_remaining: number
}

export interface JobResponse {
  job_id: string
  remaining?: number
}

export interface JobStatus {
  status: 'pending' | 'processing' | 'complete' | 'failed'
  progress?: number
  stage?: string
  result?: {
    success: boolean
    title?: string
    notionUrl?: string
  }
  error?: string
}

export interface SummaryItem {
  id: string
  title: string
  youtube_url: string
  video_id?: string
  overview?: string
  content_type?: string
  summary_format?: string
  language?: string
  created_at: string
  notion_url?: string
}

export interface ExportData {
  content: string
  filename: string
  content_type: string
}

export interface KnowledgeMapData {
  knowledgeMap: {
    topics: TopicData[]
    connections: ConnectionData[]
    totalSummaries: number
  } | null
  isStale?: boolean
  version?: number
}

export interface TopicData {
  name: string
  description: string
  facts: { fact: string; sourceVideoId?: string; sourceTitle?: string }[]
  relatedTopics: string[]
  videoIds: string[]
  importance: number
}

export interface ConnectionData {
  from: string
  to: string
  relationship: string
}

// ============ API Methods ============

export async function getProfile(): Promise<UserProfile> {
  const { data } = await api.get('/me')
  return data
}

export async function submitSummarize(
  url: string,
  summaryFormat = 'detailed',
  language = 'en'
): Promise<JobResponse> {
  const { data } = await api.post('/summarize', {
    url,
    summary_format: summaryFormat,
    language,
  })
  return data
}

export async function getJobStatus(jobId: string): Promise<JobStatus> {
  const { data } = await api.get(`/status/${jobId}`)
  return data
}

export async function getSummaryHistory(): Promise<SummaryItem[]> {
  const { data } = await api.get('/summaries')
  return data.summaries ?? []
}

export async function exportSummary(
  summaryId: string,
  format = 'markdown'
): Promise<ExportData> {
  const { data, headers } = await api.get(
    `/summaries/${summaryId}/export?format=${format}`,
    { responseType: 'text' }
  )
  const contentDisposition = headers['content-disposition'] ?? ''
  const filenameMatch = contentDisposition.match(/filename="?(.+?)"?$/)
  return {
    content: data,
    filename: filenameMatch?.[1] ?? `summary.${format === 'html' ? 'html' : 'md'}`,
    content_type: headers['content-type'] ?? 'text/plain',
  }
}

export async function getKnowledgeMap(): Promise<KnowledgeMapData> {
  const { data } = await api.get('/knowledge-map')
  return data
}

export async function buildKnowledgeMap(): Promise<{ jobId: string }> {
  const { data } = await api.post('/knowledge-map/build')
  return data
}

export async function createStripeCheckout(priceId: string): Promise<{ url: string }> {
  const { data } = await api.post('/subscription/stripe-checkout', {
    price_id: priceId,
  })
  return data
}

export default api
