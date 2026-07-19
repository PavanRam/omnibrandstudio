/**
 * Thin client for the OmniBrand Studio backend API.
 *
 * Base URL comes from PUBLIC_API_BASE_URL (exposed to the browser bundle by
 * Astro/Vite via the PUBLIC_ prefix). Defaults to the local docker stack.
 * CORS on the backend is open (`*`) and the campaign endpoints need no auth,
 * so the browser can call them directly.
 */
export const API_BASE_URL = (
  import.meta.env.PUBLIC_API_BASE_URL || 'http://localhost:8000'
).replace(/\/$/, '');

/** Campaign statuses that mean the pipeline has stopped moving. */
export const TERMINAL_STATUSES = new Set([
  'awaiting_review',
  'published',
  'failed',
  'cancelled',
  'archived',
]);

export class ApiError extends Error {
  constructor(status, detail, body) {
    super(`API request failed (${status})`);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
    this.body = body;
  }
}

async function request(path, options = {}) {
  let res;
  try {
    res = await fetch(`${API_BASE_URL}${path}`, {
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
      ...options,
    });
  } catch (networkErr) {
    // fetch throws a TypeError on network failure / CORS / server down.
    throw networkErr;
  }

  const raw = await res.text();
  let data = null;
  if (raw) {
    try {
      data = JSON.parse(raw);
    } catch {
      data = raw;
    }
  }

  if (!res.ok) {
    const detail = data && typeof data === 'object' ? data.detail : data;
    throw new ApiError(res.status, detail, data);
  }
  return data;
}

/** POST /campaigns → { campaign_id, status, poll_url } */
export function createCampaign(payload) {
  return request('/campaigns', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

/** GET /campaigns/{id}/status → lightweight status poll */
export function getCampaignStatus(campaignId) {
  return request(`/campaigns/${encodeURIComponent(campaignId)}/status`);
}

/** GET /campaigns/{id} → full detail incl. variants[] */
export function getCampaign(campaignId) {
  return request(`/campaigns/${encodeURIComponent(campaignId)}`);
}

/** GET /health → { status, checks } */
export function getHealth() {
  return request('/health');
}

/** Turn any thrown error into a human-readable message for the UI. */
export function formatApiError(err) {
  if (err instanceof ApiError) {
    const d = err.detail;
    if (Array.isArray(d)) {
      // FastAPI / Pydantic validation errors: [{ loc, msg, type }, ...]
      return d
        .map((e) => {
          const field = Array.isArray(e.loc)
            ? e.loc.filter((p) => p !== 'body').join('.')
            : '';
          return field ? `${field}: ${e.msg}` : e.msg;
        })
        .join('; ');
    }
    if (typeof d === 'string') return d;
    return `Request failed (HTTP ${err.status}).`;
  }
  if (err instanceof TypeError) {
    return `Could not reach the API at ${API_BASE_URL}. Is the backend running? (make up)`;
  }
  return err?.message || 'Unexpected error.';
}
