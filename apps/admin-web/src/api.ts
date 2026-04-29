const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8000'

export type Platform = 'wechat' | 'xhs'

export interface ImageAsset {
  id: number
  usage: string
  prompt: string
  url: string
}

export interface Draft {
  id: number
  source_id: number
  target_platform: Platform
  status: string
  title: string
  summary: string
  body_markdown: string
  body_html: string
  tags: string[]
  rewrite_params: Record<string, unknown>
  wechat_draft_media_id: string | null
  images: ImageAsset[]
}

export interface SourceItem {
  id: number
  url: string
  style_reference_url: string | null
  target_platform: Platform
  rewrite_strength: number
  image_mode: string
  source_platform: string | null
  original_title: string | null
  original_body_snapshot: string | null
  status: string
  created_at: string
}

export interface PublishJob {
  id: number
  draft_id: number
  platform: Platform
  scheduled_at: string
  execution_mode: string
  status: string
  openclaw_task_id: number | null
  failure_reason: string | null
}

export interface TaskLog {
  id: number
  stage: string
  message: string
  attachment_url: string | null
  error_code: string | null
  created_at: string
}

export interface PipelineItem {
  source: SourceItem
  draft: Draft | null
  publish_jobs: PublishJob[]
  logs: TaskLog[]
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    ...init
  })
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}))
    throw new Error(payload.detail ?? `HTTP ${response.status}`)
  }
  return response.json() as Promise<T>
}

export const api = {
  createSource: (payload: {
    url: string
    style_reference_url?: string | null
    target_platform: Platform
    rewrite_strength: number
    image_mode: 'ai' | 'none'
  }) =>
    request<SourceItem>('/api/sources', {
      method: 'POST',
      body: JSON.stringify(payload)
    }),
  generate: (sourceId: number, simulate = true, useLocalFallback = false) =>
    request<{ draft: Draft | null; openclaw_task_id: number | null }>(`/api/sources/${sourceId}/generate`, {
      method: 'POST',
      body: JSON.stringify({ simulate, use_local_fallback: useLocalFallback })
    }),
  updateDraft: (draftId: number, payload: Partial<Draft>) =>
    request<Draft>(`/api/drafts/${draftId}`, {
      method: 'PATCH',
      body: JSON.stringify(payload)
    }),
  approveDraft: (draftId: number) => request<Draft>(`/api/drafts/${draftId}/approve`, { method: 'POST' }),
  saveWechatDraft: (draftId: number) =>
    request<Draft>(`/api/drafts/${draftId}/save-wechat-draft`, { method: 'POST' }),
  createWechatAccount: (payload: {
    name: string
    app_id: string
    app_secret: string
    ip_allowlist_status: string
  }) =>
    request('/api/wechat/accounts', {
      method: 'POST',
      body: JSON.stringify(payload)
    }),
  createPublishJob: (payload: { draft_id: number; scheduled_at: string; execution_mode: 'openclaw' }) =>
    request<PublishJob>('/api/publish-jobs', {
      method: 'POST',
      body: JSON.stringify(payload)
    }),
  runScheduler: () =>
    request<{ triggered_count: number; task_ids: number[] }>('/api/scheduler/run-due', { method: 'POST' }),
  getPipeline: () => request<{ items: PipelineItem[] }>('/api/pipeline')
}
