const metaEnv = import.meta.env ?? {};
const API_BASE = metaEnv.PUBLIC_API_BASE_URL || 'http://localhost:8000';
const ACCESS_TOKEN_KEY = 'omnibrand_access_token';
const REFRESH_TOKEN_KEY = 'omnibrand_refresh_token';

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

function getStoredAccessToken() {
  if (typeof window === 'undefined') return '';
  return (window.localStorage.getItem(ACCESS_TOKEN_KEY) || '').trim();
}

function getStoredRefreshToken() {
  if (typeof window === 'undefined') return '';
  return (window.localStorage.getItem(REFRESH_TOKEN_KEY) || '').trim();
}

function setStoredTokens({ accessToken = '', refreshToken = '' }) {
  if (typeof window === 'undefined') return;
  if (accessToken) {
    window.localStorage.setItem(ACCESS_TOKEN_KEY, accessToken);
  } else {
    window.localStorage.removeItem(ACCESS_TOKEN_KEY);
  }
  if (refreshToken) {
    window.localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
  } else {
    window.localStorage.removeItem(REFRESH_TOKEN_KEY);
  }
}

function parseErrorMessage(responseBody, fallback) {
  if (responseBody && typeof responseBody === 'object') {
    const detail = responseBody.detail;
    if (typeof detail === 'string' && detail.trim()) {
      return detail;
    }
  }
  return fallback;
}

function decodeJwtClaims(token) {
  try {
    const encodedPayload = token.split('.')[1] || '';
    if (!encodedPayload) return null;
    const normalized = encodedPayload.replaceAll('-', '+').replaceAll('_', '/');
    const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, '=');
    const json = atob(padded);
    return JSON.parse(json);
  } catch {
    return null;
  }
}

function authHeaders(extra = {}) {
  const accessToken = getStoredAccessToken();
  if (accessToken) {
    return { ...extra, Authorization: `Bearer ${accessToken}` };
  }
  const apiKey = resolveApiKey();
  return apiKey ? { ...extra, 'X-API-Key': apiKey } : extra;
}

let refreshInFlight = null;

async function refreshAccessToken() {
  const currentRefreshToken = getStoredRefreshToken();
  if (!currentRefreshToken) return false;

  if (!refreshInFlight) {
    refreshInFlight = (async () => {
      const response = await fetch(`${API_BASE}/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: currentRefreshToken }),
      });

      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        setStoredTokens({ accessToken: '', refreshToken: '' });
        return false;
      }

      setStoredTokens({
        accessToken: body.access_token || '',
        refreshToken: body.refresh_token || '',
      });
      return true;
    })().finally(() => {
      refreshInFlight = null;
    });
  }

  return refreshInFlight;
}

async function fetchWithAutoRefresh(url, options = {}, allowRetry = true) {
  const response = await fetch(url, options);
  if (response.status !== 401 || !allowRetry || !getStoredAccessToken()) {
    return response;
  }

  const refreshed = await refreshAccessToken();
  if (!refreshed) {
    return response;
  }

  const baseHeaders = options.headers && typeof options.headers === 'object' ? options.headers : undefined;
  const retryHeaders = {
    ...baseHeaders,
    ...authHeaders(),
  };
  return fetch(url, { ...options, headers: retryHeaders });
}

export async function loginWithPassword(email, password) {
  const response = await fetch(`${API_BASE}/auth/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(parseErrorMessage(body, `login failed: ${response.status}`));
  }

  setStoredTokens({
    accessToken: body.access_token || '',
    refreshToken: body.refresh_token || '',
  });

  return body;
}

export async function logoutSession() {
  const accessToken = getStoredAccessToken();
  const refreshToken = getStoredRefreshToken();
  if (!accessToken) {
    setStoredTokens({ accessToken: '', refreshToken: '' });
    return;
  }

  try {
    await fetch(`${API_BASE}/auth/logout`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${accessToken}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ refresh_token: refreshToken || null }),
    });
  } finally {
    setStoredTokens({ accessToken: '', refreshToken: '' });
  }
}

export function getAccessToken() {
  return getStoredAccessToken();
}

export function getRefreshToken() {
  return getStoredRefreshToken();
}

export function clearStoredAuth() {
  setStoredTokens({ accessToken: '', refreshToken: '' });
}

export function getCurrentAuthClaims() {
  const token = getStoredAccessToken();
  return token ? decodeJwtClaims(token) : null;
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
  const accessToken = getStoredAccessToken();
  const apiKey = resolveApiKey();
  let query = '';
  if (accessToken) {
    query = `?access_token=${encodeURIComponent(accessToken)}`;
  } else if (apiKey) {
    query = `?api_key=${encodeURIComponent(apiKey)}`;
  }
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
  return resolveApiKey();
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

export async function listUsers() {
  const response = await fetchWithAutoRefresh(`${API_BASE}/users`, {
    headers: authHeaders(),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(parseErrorMessage(body, `users list failed: ${response.status}`));
  }
  return body;
}

export async function createUser({ name, email, role, password = null }) {
  const response = await fetchWithAutoRefresh(`${API_BASE}/users`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ name, email, role, password }),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(parseErrorMessage(body, `create user failed: ${response.status}`));
  }
  return body;
}
