import {
  CalendarClock,
  CheckCircle2,
  ClipboardList,
  FileText,
  Image,
  ListChecks,
  RefreshCw,
  Save,
  Send,
  Settings,
  WandSparkles,
  type LucideIcon
} from 'lucide-react'
import { FormEvent, useEffect, useMemo, useState } from 'react'
import { api, Draft, PipelineItem, Platform, SourceItem, TaskLog } from './api'
import { selectActivePipeline } from './pipelineSelection'

type View = 'workbench' | 'review' | 'schedule' | 'logs' | 'wechat'

const navItems: Array<{ id: View; label: string; icon: LucideIcon }> = [
  { id: 'workbench', label: '仿写工作台', icon: WandSparkles },
  { id: 'review', label: '草稿审核', icon: ListChecks },
  { id: 'schedule', label: '发布计划', icon: CalendarClock },
  { id: 'logs', label: '流水线日志', icon: ClipboardList },
  { id: 'wechat', label: '公众号配置', icon: Settings }
]

const statusLabels: Record<string, string> = {
  created: '已创建',
  reading: '读取中',
  rewriting: '改写中',
  image_generating: '生成图片',
  awaiting_review: '待审核',
  approved: '已审核',
  wechat_draft_saving: '保存草稿中',
  wechat_draft_saved: '草稿已保存',
  scheduled: '已排期',
  publishing: '发布中',
  succeeded: '成功',
  failed: '失败',
  canceled: '已取消'
}

function App() {
  const [activeView, setActiveView] = useState<View>('workbench')
  const [pipeline, setPipeline] = useState<PipelineItem[]>([])
  const [selectedDraft, setSelectedDraft] = useState<Draft | null>(null)
  const [activeSourceId, setActiveSourceId] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('准备就绪')
  const [sourceUrl, setSourceUrl] = useState('')
  const [styleUrl, setStyleUrl] = useState('')
  const [platform, setPlatform] = useState<Platform>('wechat')
  const [imageMode, setImageMode] = useState<'ai' | 'none'>('ai')
  const [rewriteStrength, setRewriteStrength] = useState(7)
  const [scheduleAt, setScheduleAt] = useState('')
  const [wechatForm, setWechatForm] = useState({
    name: 'AI半导体早报',
    app_id: 'wx_demo_appid',
    app_secret: '',
    ip_allowlist_status: 'configured'
  })

  const latestSelection = useMemo(
    () => selectActivePipeline(pipeline, selectedDraft, activeSourceId),
    [activeSourceId, pipeline, selectedDraft]
  )
  const latestDraft = latestSelection.draft
  const latestItem = latestSelection.item

  async function refresh() {
    const response = await api.getPipeline()
    setPipeline(response.items)
  }

  useEffect(() => {
    refresh().catch(error => setNotice(error.message))
  }, [])

  async function runAction(label: string, action: () => Promise<void>) {
    setBusy(true)
    setNotice(`${label}...`)
    try {
      await action()
      await refresh()
      setNotice(`${label}完成`)
    } catch (error) {
      await refresh().catch(() => undefined)
      setNotice(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(false)
    }
  }

  async function generateDraft(useLocalFallback = false) {
    const source = await api.createSource({
      url: sourceUrl,
      style_reference_url: styleUrl || null,
      target_platform: platform,
      rewrite_strength: rewriteStrength,
      image_mode: imageMode
    })
    setActiveSourceId(source.id)
    setSelectedDraft(null)
    const response = await api.generate(source.id, true, useLocalFallback)
    setSelectedDraft(response.draft)
    setActiveView('review')
  }

  async function handleGenerate(event: FormEvent) {
    event.preventDefault()
    if (!sourceUrl.trim()) {
      setNotice('请先输入素材链接')
      return
    }
    await runAction('模型生成草稿', () => generateDraft(false))
  }

  async function handleLocalFallback() {
    if (!sourceUrl.trim()) {
      setNotice('请先输入素材链接')
      return
    }
    await runAction('生成本地兜底稿', () => generateDraft(true))
  }

  async function handleDraftPatch(patch: Partial<Draft>) {
    if (!latestDraft) return
    await runAction('保存草稿修改', async () => {
      const updated = await api.updateDraft(latestDraft.id, patch)
      setSelectedDraft(updated)
    })
  }

  async function approveDraft() {
    if (!latestDraft) return
    await runAction('审核通过', async () => {
      setSelectedDraft(await api.approveDraft(latestDraft.id))
    })
  }

  async function saveWechatDraft() {
    if (!latestDraft) return
    await runAction('保存公众号草稿', async () => {
      setSelectedDraft(await api.saveWechatDraft(latestDraft.id))
    })
  }

  async function createSchedule() {
    if (!latestDraft || !scheduleAt) return
    await runAction('创建排期', async () => {
      await api.createPublishJob({
        draft_id: latestDraft.id,
        scheduled_at: new Date(scheduleAt).toISOString(),
        execution_mode: 'openclaw'
      })
    })
  }

  async function saveWechatAccount(event: FormEvent) {
    event.preventDefault()
    await runAction('保存公众号配置', async () => {
      await api.createWechatAccount(wechatForm)
    })
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">AD</div>
          <div>
            <h1>媒体分发</h1>
            <span>MVP Console</span>
          </div>
        </div>
        <nav>
          {navItems.map(item => {
            const Icon = item.icon
            return (
              <button
                key={item.id}
                className={activeView === item.id ? 'nav-item active' : 'nav-item'}
                onClick={() => setActiveView(item.id)}
                title={item.label}
              >
                <Icon size={18} />
                <span>{item.label}</span>
              </button>
            )
          })}
        </nav>
        <div className="status-box">
          <strong>当前状态</strong>
          <span>{notice}</span>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div>
            <p className="eyebrow">AI / 半导体 / 算力 / 大模型</p>
            <h2>{navItems.find(item => item.id === activeView)?.label}</h2>
          </div>
          <button className="icon-button" onClick={() => refresh()} disabled={busy} title="刷新流水线">
            <RefreshCw size={18} />
          </button>
        </header>

        {activeView === 'workbench' && (
          <section className="workbench">
            <form className="panel control-panel" onSubmit={handleGenerate}>
              <label>
                素材链接
                <input value={sourceUrl} onChange={event => setSourceUrl(event.target.value)} />
              </label>
              <label>
                样式参考链接
                <input value={styleUrl} onChange={event => setStyleUrl(event.target.value)} />
              </label>
              <div className="segmented">
                <button type="button" className={platform === 'wechat' ? 'selected' : ''} onClick={() => setPlatform('wechat')}>
                  公众号
                </button>
                <button type="button" className={platform === 'xhs' ? 'selected' : ''} onClick={() => setPlatform('xhs')}>
                  小红书
                </button>
              </div>
              <label>
                改写强度：{rewriteStrength}
                <input
                  type="range"
                  min="1"
                  max="10"
                  value={rewriteStrength}
                  onChange={event => setRewriteStrength(Number(event.target.value))}
                />
              </label>
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={imageMode === 'ai'}
                  onChange={event => setImageMode(event.target.checked ? 'ai' : 'none')}
                />
                AI 自动生成封面/配图
              </label>
              <button className="primary" disabled={busy}>
                <WandSparkles size={18} />
                模型生成草稿
              </button>
              <button type="button" className="secondary" disabled={busy} onClick={handleLocalFallback}>
                <FileText size={18} />
                本地兜底稿
              </button>
              <p className="form-hint">公众号默认调用模型生成；未配置 LLM_API_KEY 时可先生成本地兜底稿，但发布前建议重新模型改写。</p>
            </form>
            <Preview draft={latestDraft} source={latestItem?.source ?? null} logs={latestItem?.logs ?? []} />
          </section>
        )}

        {activeView === 'review' && (
          <section className="review-layout">
            <div className="review-stack">
              <SourceSnapshotCard source={latestItem?.source ?? null} logs={latestItem?.logs ?? []} title="素材原文快照" />
              <DraftEditor draft={latestDraft} onPatch={handleDraftPatch} disabled={busy} />
            </div>
            <div className="panel action-panel">
              <h3>审核动作</h3>
              <QualityChecklist draft={latestDraft} />
              <button onClick={approveDraft} disabled={!latestDraft || busy} className="success">
                <CheckCircle2 size={18} />
                审核通过
              </button>
              <button
                onClick={saveWechatDraft}
                disabled={!latestDraft || latestDraft.target_platform !== 'wechat' || busy}
                className="secondary"
              >
                <Save size={18} />
                保存公众号草稿
              </button>
              <ImageList draft={latestDraft} />
            </div>
          </section>
        )}

        {activeView === 'schedule' && (
          <section className="panel">
            <div className="section-heading">
              <h3>发布计划</h3>
              <button onClick={() => runAction('运行调度器', () => api.runScheduler().then(() => undefined))} disabled={busy}>
                <Send size={18} />
                运行调度器
              </button>
            </div>
            <div className="schedule-form">
              <input type="datetime-local" value={scheduleAt} onChange={event => setScheduleAt(event.target.value)} />
              <button onClick={createSchedule} disabled={!latestDraft || busy} className="primary">
                <CalendarClock size={18} />
                创建排期
              </button>
            </div>
            <PipelineTable items={pipeline} />
          </section>
        )}

        {activeView === 'logs' && (
          <section className="panel">
            <h3>流水线日志</h3>
            <LogList items={pipeline} />
          </section>
        )}

        {activeView === 'wechat' && (
          <section className="panel narrow">
            <h3>公众号配置</h3>
            <form className="settings-form" onSubmit={saveWechatAccount}>
              <label>
                公众号名称
                <input value={wechatForm.name} onChange={event => setWechatForm({ ...wechatForm, name: event.target.value })} />
              </label>
              <label>
                AppID
                <input value={wechatForm.app_id} onChange={event => setWechatForm({ ...wechatForm, app_id: event.target.value })} />
              </label>
              <label>
                AppSecret
                <input
                  type="password"
                  value={wechatForm.app_secret}
                  onChange={event => setWechatForm({ ...wechatForm, app_secret: event.target.value })}
                />
              </label>
              <label>
                IP 白名单状态
                <select
                  value={wechatForm.ip_allowlist_status}
                  onChange={event => setWechatForm({ ...wechatForm, ip_allowlist_status: event.target.value })}
                >
                  <option value="configured">已配置</option>
                  <option value="unknown">未确认</option>
                  <option value="missing">缺失</option>
                </select>
              </label>
              <button className="primary" disabled={busy}>
                <Save size={18} />
                保存配置
              </button>
            </form>
          </section>
        )}
      </main>
    </div>
  )
}

function sourceWordCount(source: SourceItem | null): number {
  return source?.original_body_snapshot ? source.original_body_snapshot.length : 0
}

function SourceSnapshotCard({
  source,
  logs = [],
  framed = true,
  title = '素材快照'
}: {
  source: SourceItem | null
  logs?: TaskLog[]
  framed?: boolean
  title?: string
}) {
  const className = `${framed ? 'panel ' : ''}source-card${!source?.original_body_snapshot ? ' empty-source' : ''}`
  const latestError =
    [...logs].reverse().find(log => log.error_code || log.stage.includes('failed')) ?? logs[logs.length - 1] ?? null

  if (!source?.original_body_snapshot) {
    if (source?.status === 'failed') {
      return (
        <div className={`${className} source-error`}>
          <strong>素材读取失败</strong>
          <p>{latestError?.message ?? '当前链接没有读取到可用于生成草稿的正文。'}</p>
          <p>请换成可公开访问的原文链接，或后续使用“粘贴正文 / OpenClaw 抓取”兜底入口。</p>
          <a href={source.url} target="_blank" rel="noreferrer">查看原始链接</a>
        </div>
      )
    }

    return (
      <div className={className}>
        <strong>{title}</strong>
        <p>生成草稿后会在这里显示真实读取到的标题、来源、字数和正文摘要。</p>
      </div>
    )
  }

  return (
    <div className={className}>
      <span className="card-kicker">{title}</span>
      <div className="source-meta">
        <strong>{source.original_title ?? '未命名素材'}</strong>
        <span>{source.source_platform ?? 'unknown'} · {sourceWordCount(source)} 字</span>
      </div>
      <p>{source.original_body_snapshot.slice(0, 260)}{source.original_body_snapshot.length > 260 ? '...' : ''}</p>
      <a href={source.url} target="_blank" rel="noreferrer">查看原始链接</a>
    </div>
  )
}

function Preview({ draft, source, logs }: { draft: Draft | null; source: SourceItem | null; logs: TaskLog[] }) {
  return (
    <article className="panel preview">
      <div className="preview-toolbar">
        <span>{draft ? statusLabels[draft.status] ?? draft.status : '暂无草稿'}</span>
        <FileText size={18} />
      </div>
      <SourceSnapshotCard source={source} logs={logs} framed={false} />
      {draft ? (
        <>
          <h3>{draft.title}</h3>
          <p className="summary">{draft.summary}</p>
          <div className="tag-row">{draft.tags.map(tag => <span key={tag}>{tag}</span>)}</div>
          <pre>{draft.body_markdown}</pre>
        </>
      ) : (
        <div className="empty-state">输入素材链接后生成公众号或小红书草稿。</div>
      )}
    </article>
  )
}

function DraftEditor({
  draft,
  onPatch,
  disabled
}: {
  draft: Draft | null
  onPatch: (patch: Partial<Draft>) => Promise<void>
  disabled: boolean
}) {
  const [localDraft, setLocalDraft] = useState<Draft | null>(draft)

  useEffect(() => setLocalDraft(draft), [draft])

  if (!localDraft) {
    return <div className="panel empty-state">还没有可审核草稿。</div>
  }

  return (
    <form
      className="panel editor"
      onSubmit={event => {
        event.preventDefault()
        onPatch({
          title: localDraft.title,
          summary: localDraft.summary,
          body_markdown: localDraft.body_markdown,
          tags: localDraft.tags
        })
      }}
    >
      <div className="editor-heading">
        <span className="card-kicker">可发文草稿</span>
        <small>{localDraft.rewrite_params.generation_engine === 'local_fallback' ? '本地兜底稿' : '模型/外部改写稿'}</small>
      </div>
      <label>
        标题
        <input value={localDraft.title} onChange={event => setLocalDraft({ ...localDraft, title: event.target.value })} />
      </label>
      <label>
        摘要
        <textarea value={localDraft.summary} onChange={event => setLocalDraft({ ...localDraft, summary: event.target.value })} />
      </label>
      <label>
        正文
        <textarea
          className="body-editor"
          value={localDraft.body_markdown}
          onChange={event => setLocalDraft({ ...localDraft, body_markdown: event.target.value })}
        />
      </label>
      <label>
        标签
        <input
          value={localDraft.tags.join('、')}
          onChange={event => setLocalDraft({ ...localDraft, tags: event.target.value.split(/[、,\s]+/).filter(Boolean) })}
        />
      </label>
      <button className="primary" disabled={disabled}>
        <Save size={18} />
        保存修改
      </button>
    </form>
  )
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map(item => String(item)).filter(Boolean) : []
}

function QualityChecklist({ draft }: { draft: Draft | null }) {
  if (!draft) {
    return <p className="muted">生成草稿后显示质量检查。</p>
  }

  const checks = (draft.rewrite_params.quality_checks ?? {}) as Record<string, unknown>
  const factNotes = asStringArray(draft.rewrite_params.fact_check_notes)
  const coveredKeywords = asStringArray(checks.keyword_coverage)
  const engine = String(draft.rewrite_params.generation_engine ?? 'unknown')
  const bodyChars = Number(checks.body_chars ?? draft.body_markdown.length)
  const paragraphCount = Number(checks.paragraph_count ?? draft.body_markdown.split(/\n\s*\n/).filter(Boolean).length)
  const noiseClean = checks.noise_clean === true || checks.noise_clean === 'true'

  return (
    <div className="quality-box">
      <div className="quality-head">
        <strong>质量检查</strong>
        <span className={engine === 'local_fallback' ? 'warning-badge' : 'ok-badge'}>
          {engine === 'local_fallback' ? '本地兜底稿' : '已通过'}
        </span>
      </div>
      <ul>
        <li>关键词覆盖：{coveredKeywords.length ? coveredKeywords.join('、') : '待检查'}</li>
        <li>正文长度：{bodyChars} 字，{paragraphCount} 段</li>
        <li>页面噪声：{noiseClean ? '已清洗' : '待人工检查'}</li>
      </ul>
      {factNotes.length > 0 && (
        <div className="fact-notes">
          <strong>人工核查点</strong>
          {factNotes.map(note => <span key={note}>{note}</span>)}
        </div>
      )}
    </div>
  )
}

function ImageList({ draft }: { draft: Draft | null }) {
  if (!draft?.images.length) return <p className="muted">暂无自动配图。</p>
  return (
    <div className="image-list">
      {draft.images.map(image => (
        <div className="image-item" key={image.id}>
          <Image size={18} />
          <span>{image.usage}</span>
          <small>{image.prompt}</small>
        </div>
      ))}
    </div>
  )
}

function PipelineTable({ items }: { items: PipelineItem[] }) {
  return (
    <div className="table">
      <div className="table-row head">
        <span>平台</span>
        <span>草稿</span>
        <span>发布时间</span>
        <span>状态</span>
      </div>
      {items.flatMap(item =>
        item.publish_jobs.map(job => (
          <div className="table-row" key={job.id}>
            <span>{job.platform === 'wechat' ? '公众号' : '小红书'}</span>
            <span>{item.draft?.title ?? '-'}</span>
            <span>{new Date(job.scheduled_at).toLocaleString()}</span>
            <span>{statusLabels[job.status] ?? job.status}</span>
          </div>
        ))
      )}
    </div>
  )
}

function LogList({ items }: { items: PipelineItem[] }) {
  const logs = items.flatMap(item =>
    item.logs.map(log => ({
      ...log,
      title: item.draft?.title ?? item.source.url,
      platform: item.source.target_platform
    }))
  )
  if (!logs.length) return <div className="empty-state">暂无日志。</div>
  return (
    <div className="log-list">
      {logs.map(log => (
        <div className="log-item" key={log.id}>
          <span className="log-stage">{log.stage}</span>
          <div>
            <strong>{log.message}</strong>
            <p>{log.title}</p>
          </div>
          <time>{new Date(log.created_at).toLocaleString()}</time>
        </div>
      ))}
    </div>
  )
}

export default App
