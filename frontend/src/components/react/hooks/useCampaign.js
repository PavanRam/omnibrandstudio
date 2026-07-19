import { useCallback, useEffect, useRef, useState } from 'react';
import {
  createCampaign,
  getCampaign,
  getCampaignStatus,
  formatApiError,
  TERMINAL_STATUSES,
} from '@/lib/api.js';

const POLL_INTERVAL_MS = 2000;
const POLL_TIMEOUT_MS = 180000; // give up after 3 minutes

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Drives the full campaign lifecycle against the backend:
 *   POST /campaigns  →  poll GET /campaigns/{id}/status  →  GET /campaigns/{id}
 *
 * Phases: 'idle' | 'submitting' | 'polling' | 'done' | 'error'
 */
export function useCampaign() {
  const [phase, setPhase] = useState('idle');
  const [campaignId, setCampaignId] = useState(null);
  const [status, setStatus] = useState(null);
  const [campaign, setCampaign] = useState(null); // full detail with variants[]
  const [error, setError] = useState(null);
  const [elapsedMs, setElapsedMs] = useState(0);

  // Set to true to abort an in-flight polling loop (cancel / unmount).
  const cancelledRef = useRef(false);

  useEffect(() => {
    // Stop polling if the component unmounts mid-run.
    return () => {
      cancelledRef.current = true;
    };
  }, []);

  const reset = useCallback(() => {
    cancelledRef.current = true;
    setPhase('idle');
    setCampaignId(null);
    setStatus(null);
    setCampaign(null);
    setError(null);
    setElapsedMs(0);
  }, []);

  const cancel = useCallback(() => {
    cancelledRef.current = true;
    setPhase('idle');
  }, []);

  const submit = useCallback(async (payload) => {
    cancelledRef.current = false;
    setPhase('submitting');
    setError(null);
    setCampaign(null);
    setStatus(null);
    setCampaignId(null);
    setElapsedMs(0);

    // 1) Create + enqueue the campaign.
    let created;
    try {
      created = await createCampaign(payload);
    } catch (err) {
      if (cancelledRef.current) return;
      setError(formatApiError(err));
      setPhase('error');
      return;
    }

    const id = created.campaign_id;
    setCampaignId(id);
    setStatus(created.status || 'queued');
    setPhase('polling');

    // 2) Poll status until the pipeline reaches a terminal state.
    const startedAt = Date.now();
    while (!cancelledRef.current) {
      if (Date.now() - startedAt > POLL_TIMEOUT_MS) {
        setError(
          'Timed out waiting for the campaign to finish. The worker may be idle, ' +
            'or generation needs a valid LLM API key in the backend .env.',
        );
        setPhase('error');
        return;
      }

      await sleep(POLL_INTERVAL_MS);
      if (cancelledRef.current) return;

      let statusResp;
      try {
        statusResp = await getCampaignStatus(id);
      } catch (err) {
        if (cancelledRef.current) return;
        setError(formatApiError(err));
        setPhase('error');
        return;
      }

      setStatus(statusResp.status);
      setElapsedMs(Date.now() - startedAt);

      if (TERMINAL_STATUSES.has(statusResp.status)) {
        // 3) Fetch full detail (variants, scores, cost).
        try {
          const full = await getCampaign(id);
          if (cancelledRef.current) return;
          setCampaign(full);
        } catch {
          // Non-fatal: we still have a terminal status to show.
        }
        setPhase('done');
        return;
      }
    }
  }, []);

  return {
    phase,
    campaignId,
    status,
    campaign,
    error,
    elapsedMs,
    submit,
    cancel,
    reset,
    isBusy: phase === 'submitting' || phase === 'polling',
  };
}
