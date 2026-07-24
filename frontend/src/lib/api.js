const metaEnv = import.meta.env ?? {};
const API_BASE = metaEnv.PUBLIC_API_BASE_URL || 'http://localhost:8000';
export const API_BASE_URL = API_BASE;
const ACCESS_TOKEN_KEY = 'omnibrand_access_token';
const REFRESH_TOKEN_KEY = 'omnibrand_refresh_token';
export const TERMINAL_STATUSES = new Set(['published', 'failed', 'cancelled', 'awaiting_review']);

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

/**
 * Proactively refresh the access token if it is within 5 minutes of expiry.
 * Call this on app load and optionally on a periodic timer.
 * Returns true if the token was refreshed or was still valid; false if the
 * refresh token is absent or the refresh request failed.
 */
export async function checkAndRefreshToken() {
  const accessToken = getStoredAccessToken();
  if (!accessToken) return Boolean(getStoredRefreshToken());

  // Decode expiry from the JWT payload (no signature verification needed here —
  // the server verifies on every API call; we only need the exp claim).
  const claims = decodeJwtClaims(accessToken);
  if (!claims || typeof claims.exp !== 'number') {
    // Can't decode: attempt a refresh to be safe.
    return refreshAccessToken();
  }

  const expiresInMs = claims.exp * 1000 - Date.now();
  const fiveMinutesMs = 5 * 60 * 1000;
  if (expiresInMs > fiveMinutesMs) {
    return true; // Still valid, no refresh needed.
  }

  return refreshAccessToken();
}

export function formatApiError(error) {
  if (error instanceof Error) {
    return error.message;
  }
  if (typeof error === 'string' && error.trim()) {
    return error;
  }
  return 'Unexpected API error';
}

export async function createCampaign(payload) {
  const response = await fetchWithAutoRefresh(`${API_BASE}/campaigns`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(parseErrorMessage(body, `campaign create failed: ${response.status}`));
  }
  return body;
}

export async function getCampaignStatus(campaignId) {
  const response = await fetchWithAutoRefresh(`${API_BASE}/campaigns/${campaignId}/status`, {
    headers: authHeaders(),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(parseErrorMessage(body, `campaign status failed: ${response.status}`));
  }
  return body;
}

export async function getCampaign(campaignId) {
  const response = await fetchWithAutoRefresh(`${API_BASE}/campaigns/${campaignId}`, {
    headers: authHeaders(),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(parseErrorMessage(body, `campaign detail failed: ${response.status}`));
  }
  return body;
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
  const response = await fetchWithAutoRefresh(`${API_BASE}/conversations`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ brand_id: brandId }),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(parseErrorMessage(body, `create conversation failed: ${response.status}`));
  }
  return body;
}

export async function fetchRecentCampaigns() {
  const response = await fetchWithAutoRefresh(`${API_BASE}/me/recent-campaigns`, {
    headers: authHeaders(),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(parseErrorMessage(body, `recent campaigns failed: ${response.status}`));
  }
  return body;
}

export async function fetchRecentConversations() {
  const response = await fetchWithAutoRefresh(`${API_BASE}/me/recent-conversations`, {
    headers: authHeaders(),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(parseErrorMessage(body, `recent conversations failed: ${response.status}`));
  }
  return body;
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

  const response = await fetchWithAutoRefresh(`${API_BASE}/campaigns/${campaignId}/events/replay?${params.toString()}`, {
    headers: authHeaders(),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(parseErrorMessage(body, `campaign replay failed: ${response.status}`));
  }
  return body;
}

export async function rerunCampaign(campaignId, fromNode, reason = null) {
  const response = await fetchWithAutoRefresh(`${API_BASE}/campaigns/${campaignId}/rerun`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ resume_from_node: fromNode, user_edit: reason }),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(parseErrorMessage(body, `campaign rerun failed: ${response.status}`));
  }
  return body;
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

  const response = await fetchWithAutoRefresh(`${API_BASE}/knowledge/brand-guides`, {
    method: 'POST',
    headers: authHeaders(),
    body: form,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(parseErrorMessage(body, `brand guide upload failed: ${response.status}`));
  }
  return body;
}

export async function listBrandGuides(brandId) {
  const response = await fetchWithAutoRefresh(`${API_BASE}/knowledge/brand-guides/${brandId}`, {
    headers: authHeaders(),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(parseErrorMessage(body, `brand guide list failed: ${response.status}`));
  }
  return body;
}

export async function uploadCustomerSegments({ brandId, locale, version, file }) {
  const form = new FormData();
  form.append('brand_id', brandId);
  form.append('locale', locale);
  form.append('version', version);
  form.append('segment_file', file);

  const response = await fetchWithAutoRefresh(`${API_BASE}/knowledge/segments`, {
    method: 'POST',
    headers: authHeaders(),
    body: form,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(parseErrorMessage(body, `segment upload failed: ${response.status}`));
  }
  return body;
}

export async function listCustomerSegments(brandId, locale, version = '') {
  const params = new URLSearchParams({ locale });
  if (version) params.set('version', version);

  const response = await fetchWithAutoRefresh(`${API_BASE}/knowledge/segments/${brandId}?${params.toString()}`, {
    headers: authHeaders(),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(parseErrorMessage(body, `segment list failed: ${response.status}`));
  }
  return body;
}

export async function getAllowedLocales(brandId) {
  const response = await fetchWithAutoRefresh(
    `${API_BASE}/knowledge/brands/${brandId}/allowed-locales`,
    { headers: authHeaders() },
  );
  const body = await response.json().catch(() => ({}));
  if (!response.ok) return { allowed_locales: [] };
  return body;
}

export async function setAllowedLocales(brandId, locales) {
  const response = await fetchWithAutoRefresh(
    `${API_BASE}/knowledge/brands/${brandId}/allowed-locales`,
    {
      method: 'PATCH',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ allowed_locales: locales }),
    },
  );
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(parseErrorMessage(body, `set allowed locales failed: ${response.status}`));
  }
  return body;
}

export async function listGoldenSets(brandId) {
  const response = await fetchWithAutoRefresh(`${API_BASE}/knowledge/golden-dataset/sets/${brandId}`, {
    headers: authHeaders(),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(parseErrorMessage(body, `golden set list failed: ${response.status}`));
  }
  return body;
}

export async function openGoldenSet({ brandId, locale = 'en-US', guideVersion = null }) {
  const response = await fetchWithAutoRefresh(`${API_BASE}/knowledge/golden-dataset/sets`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ brand_id: brandId, locale, guide_version: guideVersion }),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(parseErrorMessage(body, `golden set create failed: ${response.status}`));
  }
  return body;
}

export async function activateGoldenSet({ brandId, setId }) {
  const response = await fetchWithAutoRefresh(
    `${API_BASE}/knowledge/golden-dataset/sets/${setId}/activate`,
    {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ brand_id: brandId }),
    },
  );
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(parseErrorMessage(body, `golden set activate failed: ${response.status}`));
  }
  return body;
}

export async function listGoldenExamples(brandId, { status = '', setId = '' } = {}) {
  const params = new URLSearchParams();
  if (status) params.set('status_filter', status);
  if (setId) params.set('set_id', setId);
  const qs = params.toString();
  const suffix = qs ? `?${qs}` : '';
  const response = await fetchWithAutoRefresh(
    `${API_BASE}/knowledge/golden-dataset/${brandId}${suffix}`,
    { headers: authHeaders() },
  );
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(parseErrorMessage(body, `golden example list failed: ${response.status}`));
  }
  return body;
}

export async function promoteGoldenExample({ brandId, exampleId }) {
  const response = await fetchWithAutoRefresh(
    `${API_BASE}/knowledge/golden-dataset/${exampleId}/promote`,
    {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ brand_id: brandId }),
    },
  );
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(parseErrorMessage(body, `golden example promote failed: ${response.status}`));
  }
  return body;
}

export async function deleteGoldenExample({ brandId, exampleId }) {
  const params = new URLSearchParams({ brand_id: brandId });
  const response = await fetchWithAutoRefresh(
    `${API_BASE}/knowledge/golden-dataset/${exampleId}?${params.toString()}`,
    { method: 'DELETE', headers: authHeaders() },
  );
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(parseErrorMessage(body, `golden example delete failed: ${response.status}`));
  }
  return body;
}

export async function fetchPendingReviews({ status = 'pending', limit = 20, offset = 0 } = {}) {
  const params = new URLSearchParams({ status, limit: String(limit), offset: String(offset) });
  const response = await fetchWithAutoRefresh(`${API_BASE}/reviews?${params.toString()}`, {
    headers: authHeaders(),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(parseErrorMessage(body, `pending reviews fetch failed: ${response.status}`));
  }
  return body;
}

export async function decideReview(reviewRequestId, decision, { reviewerNote = null, editedContent = null } = {}) {
  const response = await fetchWithAutoRefresh(`${API_BASE}/reviews/${reviewRequestId}/decide`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({
      decision,
      reviewer_note: reviewerNote,
      edited_content: editedContent,
    }),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(parseErrorMessage(body, `review decision failed: ${response.status}`));
  }
  return body;
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
