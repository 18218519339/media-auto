const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8000';
export async function request(path, init) {
    const response = await fetch(`${API_BASE}${path}`, {
        headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
        ...init
    });
    if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail ?? `HTTP ${response.status}`);
    }
    return response.json();
}
export const api = {
    createSource: (payload) => request('/api/sources', {
        method: 'POST',
        body: JSON.stringify(payload)
    }),
    generate: (sourceId, simulate = true) => request(`/api/sources/${sourceId}/generate`, {
        method: 'POST',
        body: JSON.stringify({ simulate })
    }),
    updateDraft: (draftId, payload) => request(`/api/drafts/${draftId}`, {
        method: 'PATCH',
        body: JSON.stringify(payload)
    }),
    approveDraft: (draftId) => request(`/api/drafts/${draftId}/approve`, { method: 'POST' }),
    saveWechatDraft: (draftId) => request(`/api/drafts/${draftId}/save-wechat-draft`, { method: 'POST' }),
    createWechatAccount: (payload) => request('/api/wechat/accounts', {
        method: 'POST',
        body: JSON.stringify(payload)
    }),
    createPublishJob: (payload) => request('/api/publish-jobs', {
        method: 'POST',
        body: JSON.stringify(payload)
    }),
    runScheduler: () => request('/api/scheduler/run-due', { method: 'POST' }),
    getPipeline: () => request('/api/pipeline')
};
