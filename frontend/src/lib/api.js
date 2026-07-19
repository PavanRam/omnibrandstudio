const metaEnv = import.meta.env ?? {};
const API_BASE = metaEnv.PUBLIC_API_BASE_URL || 'http://localhost:8000';

function resolveApiKey() {
  const configured = (metaEnv.PUBLIC_API_KEY || '').trim();
  if (configured) return configured;

  if (typeof window !== 'undefined') {
    const stored = window.localStorage.getItem('omnibrand_api_key') || '';
    if (stored.trim()) return stored.trim();

    if (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') {
      return 'dev-local-chat-key';
    }
  }

  return '';
}

const API_KEY = resolveApiKey();

function authHeaders(extra = {}) {
  return API_KEY ? { ...extra, 'X-API-Key': API_KEY } : extra;
}

export async function createConversation(brandId) {
  const response = await fetch(`${API_BASE}/conversations`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ brand_id: brandId }),
  });
  if (!response.ok) {
    throw new Error(`create conversation failed: ${response.status}`);
  }
  return response.json();
}

export async function fetchRecentCampaigns() {
  const response = await fetch(`${API_BASE}/me/recent-campaigns`, {
    headers: authHeaders(),
  });
  if (!response.ok) {
    throw new Error(`recent campaigns failed: ${response.status}`);
  }
  return response.json();
}

export async function fetchRecentConversations() {
  const response = await fetch(`${API_BASE}/me/recent-conversations`, {
    headers: authHeaders(),
  });
  if (!response.ok) {
    throw new Error(`recent conversations failed: ${response.status}`);
  }
  return response.json();
}

export function openConversationSocket(conversationId) {
  const http = new URL(API_BASE);
  const wsProto = http.protocol === 'https:' ? 'wss:' : 'ws:';
  const query = API_KEY ? `?api_key=${encodeURIComponent(API_KEY)}` : '';
  const wsUrl = `${wsProto}//${http.host}/conversations/${conversationId}${query}`;
  return new WebSocket(wsUrl, []);
}

export function openCampaignEventStream(campaignId) {
  return new EventSource(`${API_BASE}/campaigns/${campaignId}/stream`);
}

export async function fetchCampaignReplay(campaignId, limit = 60, beforeEventId = null) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (beforeEventId) {
    params.set('before_event_id', beforeEventId);
  }

  const response = await fetch(`${API_BASE}/campaigns/${campaignId}/events/replay?${params.toString()}`, {
    headers: authHeaders(),
  });
  if (!response.ok) {
    throw new Error(`campaign replay failed: ${response.status}`);
  }
  return response.json();
}

export async function rerunCampaign(campaignId, fromNode, reason = null) {
  const response = await fetch(`${API_BASE}/campaigns/${campaignId}/rerun`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ resume_from_node: fromNode, user_edit: reason }),
  });
  if (!response.ok) {
    throw new Error(`campaign rerun failed: ${response.status}`);
  }
  return response.json();
}

export function getApiKey() {
  return API_KEY;
}

export async function uploadBrandGuide({ brandId, locale, version, file }) {
  const form = new FormData();
  form.append('brand_id', brandId);
  form.append('locale', locale);
  form.append('version', version);
  form.append('guide_file', file);

  const response = await fetch(`${API_BASE}/knowledge/brand-guides`, {
    method: 'POST',
    headers: authHeaders(),
    body: form,
  });
  if (!response.ok) {
    throw new Error(`brand guide upload failed: ${response.status}`);
  }
  return response.json();
}

export async function listBrandGuides(brandId) {
  const response = await fetch(`${API_BASE}/knowledge/brand-guides/${brandId}`, {
    headers: authHeaders(),
  });
  if (!response.ok) {
    throw new Error(`brand guide list failed: ${response.status}`);
  }
  return response.json();
}

export async function uploadCustomerSegments({ brandId, locale, version, file }) {
  const form = new FormData();
  form.append('brand_id', brandId);
  form.append('locale', locale);
  form.append('version', version);
  form.append('segment_file', file);

  const response = await fetch(`${API_BASE}/knowledge/segments`, {
    method: 'POST',
    headers: authHeaders(),
    body: form,
  });
  if (!response.ok) {
    throw new Error(`segment upload failed: ${response.status}`);
  }
  return response.json();
}

export async function listCustomerSegments(brandId, locale, version = '') {
  const params = new URLSearchParams({ locale });
  if (version) params.set('version', version);

  const response = await fetch(`${API_BASE}/knowledge/segments/${brandId}?${params.toString()}`, {
    headers: authHeaders(),
  });
  if (!response.ok) {
    throw new Error(`segment list failed: ${response.status}`);
  }
  return response.json();
}
