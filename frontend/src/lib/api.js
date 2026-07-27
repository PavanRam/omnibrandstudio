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

function notifySessionExpired() {
  setStoredTokens({ accessToken: '', refreshToken: '' });
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new Event('obs:session-expired'));
  }
}

async function fetchWithAutoRefresh(url, options = {}, allowRetry = true) {
  const response = await fetch(url, options);
  if (response.status !== 401 || !allowRetry || !getStoredAccessToken()) {
    return response;
  }

  const refreshed = await refreshAccessToken();
  if (!refreshed) {
    // Access token was rejected and the refresh attempt didn't recover it —
    // this is an unrecoverable expired session, not just a transient 401.
    // Without this, the UI silently stays on whatever page it was on,
    // showing scattered "401" errors per request forever (the bug this
    // fixes) instead of sending the user back to log in.
    notifySessionExpired();
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
  const response = await fetchWithAutoRefresh(`${API_BASE}/conversations`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ brand_id: brandId }),
  });
  if (!response.ok) {
    throw new Error(`create conversation failed: ${response.status}`);
  }
  return response.json();
}

export async function fetchRecentCampaigns({ includeArchived = false } = {}) {
  const params = includeArchived ? '?include_archived=true' : '';
  const response = await fetchWithAutoRefresh(`${API_BASE}/me/recent-campaigns${params}`, {
    headers: authHeaders(),
  });
  if (!response.ok) {
    throw new Error(`recent campaigns failed: ${response.status}`);
  }
  return response.json();
}

export async function archiveCampaign(campaignId) {
  const response = await fetchWithAutoRefresh(`${API_BASE}/campaigns/${campaignId}/archive`, {
    method: 'POST',
    headers: authHeaders(),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(parseErrorMessage(body, `archive campaign failed: ${response.status}`));
  }
  return body;
}

export async function fetchRecentConversations() {
  const response = await fetchWithAutoRefresh(`${API_BASE}/me/recent-conversations`, {
    headers: authHeaders(),
  });
  if (!response.ok) {
    throw new Error(`recent conversations failed: ${response.status}`);
  }
  return response.json();
}

export async function archiveConversation(conversationId) {
  const response = await fetchWithAutoRefresh(`${API_BASE}/conversations/${conversationId}/archive`, {
    method: 'POST',
    headers: authHeaders(),
  });
  if (!response.ok) {
    throw new Error(`archive conversation failed: ${response.status}`);
  }
  return response.json();
}

export async function fetchConversationMessages(conversationId) {
  const response = await fetchWithAutoRefresh(`${API_BASE}/conversations/${conversationId}/messages`, {
    headers: authHeaders(),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(parseErrorMessage(body, `conversation history failed: ${response.status}`));
  }
  return body;
}

export async function fetchUnreadNotificationCount() {
  const response = await fetchWithAutoRefresh(`${API_BASE}/notifications/unread-count`, {
    headers: authHeaders(),
  });
  if (!response.ok) {
    throw new Error(`unread notification count failed: ${response.status}`);
  }
  return response.json();
}

export async function fetchNotifications() {
  const response = await fetchWithAutoRefresh(`${API_BASE}/notifications`, {
    headers: authHeaders(),
  });
  if (!response.ok) {
    throw new Error(`fetch notifications failed: ${response.status}`);
  }
  return response.json();
}

export async function markNotificationRead(notificationId) {
  const response = await fetchWithAutoRefresh(`${API_BASE}/notifications/${notificationId}/read`, {
    method: 'POST',
    headers: authHeaders(),
  });
  if (!response.ok) {
    throw new Error(`mark notification read failed: ${response.status}`);
  }
  return response.json();
}

export async function markAllNotificationsRead() {
  const response = await fetchWithAutoRefresh(`${API_BASE}/notifications/read-all`, {
    method: 'POST',
    headers: authHeaders(),
  });
  if (!response.ok) {
    throw new Error(`mark all notifications read failed: ${response.status}`);
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

  const response = await fetchWithAutoRefresh(
    `${API_BASE}/campaigns/${campaignId}/events/replay?${params.toString()}`,
    { headers: authHeaders() },
  );
  if (!response.ok) {
    throw new Error(`campaign replay failed: ${response.status}`);
  }
  return response.json();
}

export async function rerunCampaign(campaignId, fromNode, reason = null, variantTaskId = null) {
  const response = await fetchWithAutoRefresh(`${API_BASE}/campaigns/${campaignId}/rerun`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({
      resume_from_node: fromNode,
      user_edit: reason,
      variant_task_id: variantTaskId,
    }),
  });
  if (!response.ok) {
    throw new Error(`campaign rerun failed: ${response.status}`);
  }
  return response.json();
}

export async function runCampaignAnyway(conversationId) {
  const response = await fetchWithAutoRefresh(`${API_BASE}/conversations/${conversationId}/run-anyway`, {
    method: 'POST',
    headers: authHeaders(),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(parseErrorMessage(body, `run campaign failed: ${response.status}`));
  }
  return body;
}

// Fetch the channels and locales a specific brand is entitled to use.
// Calls GET /brands/{brandId}/entitlements — non-admin, scoped to the caller's org.
export async function fetchBrandEntitlements(brandId) {
  const response = await fetchWithAutoRefresh(`${API_BASE}/brands/${encodeURIComponent(brandId)}/entitlements`, {
    headers: authHeaders(),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(parseErrorMessage(body, `brand entitlements fetch failed: ${response.status}`));
  }
  return body;
}

export async function fetchSegmentOptions(brandId) {
  const response = await fetchWithAutoRefresh(`${API_BASE}/knowledge/segments/${brandId}/options`, {
    headers: authHeaders(),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(parseErrorMessage(body, `segment options fetch failed: ${response.status}`));
  }
  return body;
}

export async function estimateBudget(conversationId, { channels = [], locales = [], audienceSegments = [] } = {}) {
  const response = await fetchWithAutoRefresh(
    `${API_BASE}/conversations/${conversationId}/estimate-budget`,
    {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ channels, locales, audience_segments: audienceSegments }),
    },
  );
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(parseErrorMessage(body, `budget estimate failed: ${response.status}`));
  }
  return body;
}

export async function listBrands() {
  const response = await fetchWithAutoRefresh(`${API_BASE}/brands`, {
    headers: authHeaders(),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(parseErrorMessage(body, `brands fetch failed: ${response.status}`));
  }
  return body;
}

export async function createBrand(name, sourceLocale = 'en-US') {
  const response = await fetchWithAutoRefresh(`${API_BASE}/brands`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ name, source_locale: sourceLocale }),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(parseErrorMessage(body, `create brand failed: ${response.status}`));
  }
  return body;
}

export async function updateUserBrands(userId, brandIds) {
  const response = await fetchWithAutoRefresh(`${API_BASE}/users/${userId}/brands`, {
    method: 'PATCH',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ brand_ids: brandIds }),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(parseErrorMessage(body, `update user brands failed: ${response.status}`));
  }
  return body;
}

export async function updateUser(userId, data) {
  const response = await fetchWithAutoRefresh(`${API_BASE}/users/${userId}`, {
    method: 'PATCH',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(data),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(parseErrorMessage(body, `update user failed: ${response.status}`));
  }
  return body;
}


export async function getBrandConfig(brandId) {
  const response = await fetchWithAutoRefresh(`${API_BASE}/brands/${brandId}/config`, {
    headers: authHeaders(),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(parseErrorMessage(body, `brand config fetch failed: ${response.status}`));
  }
  return body;
}

export async function updateBrandConfig(brandId, { name, industry, keyClaims, channels, locales }) {
  const response = await fetchWithAutoRefresh(`${API_BASE}/brands/${brandId}/config`, {
    method: 'PATCH',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({
      name,
      industry,
      key_claims: keyClaims,
      channels,
      locales,
    }),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(parseErrorMessage(body, `brand config update failed: ${response.status}`));
  }
  return body;
}

export async function setBriefField(conversationId, field, value) {
  const response = await fetchWithAutoRefresh(
    `${API_BASE}/conversations/${conversationId}/set-brief-field`,
    {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ field, value }),
    },
  );
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(parseErrorMessage(body, `set brief field failed: ${response.status}`));
  }
  return body;
}

export async function fetchCampaign(campaignId) {
  const response = await fetchWithAutoRefresh(`${API_BASE}/campaigns/${campaignId}`, {
    headers: authHeaders(),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(parseErrorMessage(body, `campaign fetch failed: ${response.status}`));
  }
  return body;
}

export async function sendCampaignToReview(campaignId) {
  const response = await fetchWithAutoRefresh(`${API_BASE}/campaigns/${campaignId}/send-to-review`, {
    method: 'POST',
    headers: authHeaders(),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(parseErrorMessage(body, `send to review failed: ${response.status}`));
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
  if (!response.ok) {
    throw new Error(`brand guide upload failed: ${response.status}`);
  }
  return response.json();
}

export async function listBrandGuides(brandId) {
  const response = await fetchWithAutoRefresh(`${API_BASE}/knowledge/brand-guides/${brandId}`, {
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

  const response = await fetchWithAutoRefresh(`${API_BASE}/knowledge/segments`, {
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

  const response = await fetchWithAutoRefresh(`${API_BASE}/knowledge/segments/${brandId}?${params.toString()}`, {
    headers: authHeaders(),
  });
  if (!response.ok) {
    throw new Error(`segment list failed: ${response.status}`);
  }
  return response.json();
}

export async function listGoldenSets(brandId) {
  const response = await fetchWithAutoRefresh(`${API_BASE}/knowledge/golden-dataset/sets/${brandId}`, {
    headers: authHeaders(),
  });
  if (!response.ok) {
    throw new Error(`golden set list failed: ${response.status}`);
  }
  return response.json();
}

export async function openGoldenSet({ brandId, locale = 'en-US', guideVersion = null }) {
  const response = await fetchWithAutoRefresh(`${API_BASE}/knowledge/golden-dataset/sets`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ brand_id: brandId, locale, guide_version: guideVersion }),
  });
  if (!response.ok) {
    throw new Error(`golden set create failed: ${response.status}`);
  }
  return response.json();
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
  if (!response.ok) {
    throw new Error(`golden set activate failed: ${response.status}`);
  }
  return response.json();
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
  if (!response.ok) {
    throw new Error(`golden example list failed: ${response.status}`);
  }
  return response.json();
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
  if (!response.ok) {
    throw new Error(`golden example promote failed: ${response.status}`);
  }
  return response.json();
}

export async function deleteGoldenExample({ brandId, exampleId }) {
  const params = new URLSearchParams({ brand_id: brandId });
  const response = await fetchWithAutoRefresh(
    `${API_BASE}/knowledge/golden-dataset/${exampleId}?${params.toString()}`,
    { method: 'DELETE', headers: authHeaders() },
  );
  if (!response.ok) {
    throw new Error(`golden example delete failed: ${response.status}`);
  }
  return response.json();
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

export async function createUser({ name, email, role, password = null, brandIds = null }) {
  const response = await fetchWithAutoRefresh(`${API_BASE}/users`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ name, email, role, password, brand_ids: brandIds }),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(parseErrorMessage(body, `create user failed: ${response.status}`));
  }
  return body;
}

export async function fetchCampaignStats() {
  const response = await fetchWithAutoRefresh(`${API_BASE}/campaigns/stats`, {
    headers: authHeaders(),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(parseErrorMessage(body, `campaign stats fetch failed: ${response.status}`));
  }
  return body;
}

