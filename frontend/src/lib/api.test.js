import test from 'node:test';
import assert from 'node:assert/strict';

import { rerunCampaign } from './api.js';

test('rerunCampaign sends backend-compatible payload fields', async () => {
  let capturedUrl = '';
  let capturedInit = null;

  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    capturedUrl = url;
    capturedInit = init;
    return {
      ok: true,
      async json() {
        return { revision_id: 'rev-1' };
      },
    };
  };

  try {
    const result = await rerunCampaign('campaign-123', 'content_generator', 'retry this stage');
    assert.equal(result.revision_id, 'rev-1');
    assert.equal(capturedUrl, 'http://localhost:8000/campaigns/campaign-123/rerun');
    assert.equal(capturedInit.method, 'POST');

    const body = JSON.parse(capturedInit.body);
    assert.equal(body.resume_from_node, 'content_generator');
    assert.equal(body.user_edit, 'retry this stage');
    assert.ok(!Object.prototype.hasOwnProperty.call(body, 'from_node'));
    assert.ok(!Object.prototype.hasOwnProperty.call(body, 'reason'));
  } finally {
    globalThis.fetch = originalFetch;
  }
});
