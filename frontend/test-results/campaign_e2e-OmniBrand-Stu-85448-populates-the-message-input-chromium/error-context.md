# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: campaign_e2e.spec.js >> OmniBrand Studio — Campaign E2E >> 2 · Sample brief chip populates the message input
- Location: tests\e2e\campaign_e2e.spec.js:160:3

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: getByRole('button', { name: /show me an example brief/i })
Expected: visible
Timeout: 10000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" with timeout 10000ms
  - waiting for getByRole('button', { name: /show me an example brief/i })

```

```yaml
- link "Skip to main content":
  - /url: "#main-content"
- complementary "Sidebar":
  - link "OmniBrand Studio — home":
    - /url: /
    - text: OmniBrand Studio
  - button "Collapse sidebar"
  - navigation "Primary":
    - heading "Create" [level=2]
    - list:
      - listitem:
        - link "Workspace":
          - /url: /app
      - listitem:
        - link "Campaigns":
          - /url: /gallery
    - heading "Manage" [level=2]
    - list:
      - listitem:
        - link "Admin Panel":
          - /url: /admin
  - button "Made with by Adobe Team": Made withby Adobe Team
- banner:
  - heading "Campaign Studio" [level=1]
  - switch "Switch to dark mode"
  - button "Notifications, 2 unread"
  - button "U User"
  - button "Log out"
- main:
  - paragraph: Workspace
  - heading "Campaign Studio" [level=1]
  - paragraph: Chat to build a brief, then watch the pipeline run in real time.
  - text: Chat
  - button "New conversation"
  - heading "Conversations" [level=2]
  - button "Refresh conversations"
  - button "f2f36d54-b90… processing · 4m ago":
    - paragraph: f2f36d54-b90…
    - paragraph: processing · 4m ago
  - button "4996ea8d-39e… collecting · 2h ago":
    - paragraph: 4996ea8d-39e…
    - paragraph: collecting · 2h ago
  - button "d231a031-215… collecting · 8h ago":
    - paragraph: d231a031-215…
    - paragraph: collecting · 8h ago
  - button "824755ff-a85… collecting · 9h ago":
    - paragraph: 824755ff-a85…
    - paragraph: collecting · 9h ago
  - button "d47a2d95-517… collecting · 9h ago":
    - paragraph: d47a2d95-517…
    - paragraph: collecting · 9h ago
  - button "828b3802-a6c… collecting · 1d ago":
    - paragraph: 828b3802-a6c…
    - paragraph: collecting · 1d ago
  - button "8225b7c8-6e6… processing · 1d ago":
    - paragraph: 8225b7c8-6e6…
    - paragraph: processing · 1d ago
  - button "683c4771-474… collecting · 1d ago":
    - paragraph: 683c4771-474…
    - paragraph: collecting · 1d ago
  - button "4d3911a3-770… collecting · 1d ago":
    - paragraph: 4d3911a3-770…
    - paragraph: collecting · 1d ago
  - button "cd6e52e8-1e6… processing · 1d ago":
    - paragraph: cd6e52e8-1e6…
    - paragraph: processing · 1d ago
  - button "ab42f77a-805… collecting · 1d ago":
    - paragraph: ab42f77a-805…
    - paragraph: collecting · 1d ago
  - button "fd3579d4-1df… collecting · 1d ago":
    - paragraph: fd3579d4-1df…
    - paragraph: collecting · 1d ago
  - heading "Campaign Studio" [level=2]
  - paragraph: f2f36d54-b90d-49e2-921f-97df7822cd70
  - text: campaign discovery Campaign cost —·Tokens —
  - paragraph: Resumed conversation f2f36d54-b90d-49e2-921f-97df7822cd70. Continue the brief or run campaign when ready.
  - button "What is the current campaign status?"
  - button "What happened in the last step?"
  - button "Show outputs from content_generator"
  - textbox "Describe your campaign..."
  - button "Send message" [disabled]
  - button "Brief"
  - button "Pipeline"
  - text: 5 of 5 complete 100%
  - list:
    - listitem:
      - paragraph: Objective
      - paragraph: drive qualified demo requests
    - listitem:
      - paragraph: Channels
      - text: instagram x email
    - listitem:
      - paragraph: Locales
      - text: en-us es-es
    - listitem:
      - paragraph: Audience segments
      - text: Young adults aged 20-30 (Gen Z and Millennials who value experiences exploration social proof and breaking their daily routine)
    - listitem:
      - paragraph: Token budget
      - paragraph: 5,000 tokens
  - paragraph: When every field is complete, send “run campaign” to enqueue execution.
```

# Test source

```ts
  71  | async function injectAuth(page, accessToken, refreshToken) {
  72  |   await page.addInitScript(
  73  |     ([atKey, rtKey, at, rt]) => {
  74  |       localStorage.setItem(atKey, at);
  75  |       if (rt) localStorage.setItem(rtKey, rt);
  76  |     },
  77  |     [LS_ACCESS_KEY, LS_REFRESH_KEY, accessToken, refreshToken],
  78  |   );
  79  | }
  80  | 
  81  | /**
  82  |  * Seed a minimal campaign via POST /campaigns so gallery tests have data.
  83  |  * Returns the campaign_id, or null if seeding failed.
  84  |  */
  85  | async function seedCampaign(accessToken) {
  86  |   const BRAND_ID = '00000000-0000-0000-0000-000000000002';
  87  |   const res = await fetch(`${API}/campaigns`, {
  88  |     method: 'POST',
  89  |     headers: {
  90  |       'Content-Type': 'application/json',
  91  |       Authorization: `Bearer ${accessToken}`,
  92  |     },
  93  |     body: JSON.stringify({
  94  |       brand_id: BRAND_ID,
  95  |       objective: 'E2E smoke test campaign — automated',
  96  |       target_audience: 'QA engineers 25-44',
  97  |       key_messages: ['Test message 1'],
  98  |       channels: ['email'],
  99  |       locales: ['en-US'],
  100 |       audience_segments: ['25-34'],
  101 |       token_budget: 10000,
  102 |       raw_text: SAMPLE_BRIEF,
  103 |     }),
  104 |   });
  105 |   if (!res.ok) {
  106 |     console.warn(`Seed campaign failed: ${res.status} ${await res.text()}`);
  107 |     return null;
  108 |   }
  109 |   const body = await res.json();
  110 |   return body.campaign_id || body.id || null;
  111 | }
  112 | 
  113 | // ---------------------------------------------------------------------------
  114 | // Test suite
  115 | // ---------------------------------------------------------------------------
  116 | 
  117 | test.describe('OmniBrand Studio — Campaign E2E', () => {
  118 |   let accessToken = '';
  119 |   let refreshToken = '';
  120 |   let launchedCampaignId = '';
  121 |   let seededCampaignId = '';
  122 | 
  123 |   test.beforeAll(async () => {
  124 |     ({ accessToken, refreshToken } = await apiLogin());
  125 |     // Pre-seed a campaign so gallery tests 5+6 always have at least one card
  126 |     seededCampaignId = await seedCampaign(accessToken) ?? '';
  127 |     if (seededCampaignId) {
  128 |       console.log(`Pre-seeded campaign: ${seededCampaignId}`);
  129 |     }
  130 |   });
  131 | 
  132 |   // ─────────────────────────────────────────────────────────────────────────
  133 |   // 1. Login via UI modal
  134 |   // ─────────────────────────────────────────────────────────────────────────
  135 |   test('1 · Login via the login modal', async ({ page }) => {
  136 |     // Navigate unauthenticated to the landing page
  137 |     await page.goto('/');
  138 | 
  139 |     // Click the login button to open the modal
  140 |     const loginButton = page.getByRole('button', { name: /log in/i });
  141 |     await expect(loginButton).toBeVisible({ timeout: 10_000 });
  142 |     await loginButton.click();
  143 | 
  144 |     // Fill credentials and sign in
  145 |     await page.getByLabel(/email/i).fill(ADMIN_EMAIL);
  146 |     await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
  147 |     await page.getByRole('button', { name: /sign in/i }).click();
  148 | 
  149 |     // Should redirect to /app after login
  150 |     await expect(page).toHaveURL(/\/app/, { timeout: 20_000 });
  151 |     // Workspace heading visible — use first() to handle multiple "Campaign Studio" headings
  152 |     await expect(page.getByRole('heading', { name: /campaign studio/i }).first()).toBeVisible({
  153 |       timeout: 10_000,
  154 |     });
  155 |   });
  156 | 
  157 |   // ─────────────────────────────────────────────────────────────────────────
  158 |   // 2. Sample brief chip populates the input
  159 |   // ─────────────────────────────────────────────────────────────────────────
  160 |   test('2 · Sample brief chip populates the message input', async ({ page }) => {
  161 |     await injectAuth(page, accessToken, refreshToken);
  162 |     await page.goto('/app');
  163 | 
  164 |     // Workspace should load with Campaign Studio heading (use .first() — multiple h1/h2 share this name)
  165 |     await expect(page.getByRole('heading', { name: /campaign studio/i }).first()).toBeVisible({
  166 |       timeout: 15_000,
  167 |     });
  168 | 
  169 |     // The chip is only rendered when the conversation is empty (empty state)
  170 |     const chip = page.getByRole('button', { name: /show me an example brief/i });
> 171 |     await expect(chip).toBeVisible({ timeout: 10_000 });
      |                        ^ Error: expect(locator).toBeVisible() failed
  172 |     await chip.click();
  173 | 
  174 |     // After clicking the chip, sendPrompt fires — expect the user message bubble to appear
  175 |     await expect(
  176 |       page.locator('[class*="message"], .message-bubble').first(),
  177 |     ).toBeVisible({ timeout: 15_000 });
  178 |   });
  179 | 
  180 |   // ─────────────────────────────────────────────────────────────────────────
  181 |   // 3. Submit brief and launch campaign
  182 |   // ─────────────────────────────────────────────────────────────────────────
  183 |   test('3 · Submit brief, confirm, and launch campaign', async ({ page }) => {
  184 |     test.setTimeout(200_000);
  185 |     await injectAuth(page, accessToken, refreshToken);
  186 |     await page.goto('/app');
  187 | 
  188 |     await expect(page.getByRole('heading', { name: /campaign studio/i }).first()).toBeVisible({
  189 |       timeout: 15_000,
  190 |     });
  191 | 
  192 |     // Type the brief in the chat input
  193 |     const input = page
  194 |       .getByPlaceholder(/type a message/i)
  195 |       .or(page.locator('textarea').last())
  196 |       .or(page.locator('input[type="text"]').last());
  197 |     await input.fill(SAMPLE_BRIEF);
  198 |     await input.press('Enter');
  199 | 
  200 |     // Wait for assistant to respond
  201 |     await expect(page.locator('.message-bubble, [class*="message"]').last()).toBeVisible({
  202 |       timeout: 45_000,
  203 |     });
  204 | 
  205 |     // If a launch/confirm button appears, click it; otherwise type "yes"
  206 |     const launchBtn = page.getByRole('button', { name: /launch|confirm|start campaign/i });
  207 |     if (await launchBtn.isVisible({ timeout: 8_000 }).catch(() => false)) {
  208 |       await launchBtn.click();
  209 |     } else {
  210 |       // The copilot may have auto-confirmed; send an explicit confirmation
  211 |       await input.fill('Yes, launch it.');
  212 |       await input.press('Enter');
  213 |     }
  214 | 
  215 |     // Wait up to 60s for a campaign to appear in the API list
  216 |     await page.waitForTimeout(5_000);
  217 |     const listRes = await fetch(`${API}/campaigns`, {
  218 |       headers: { Authorization: `Bearer ${accessToken}` },
  219 |     });
  220 |     const listBody = await listRes.json().catch(() => ({ campaigns: [] }));
  221 |     const latest = (listBody.campaigns || [])[0];
  222 |     expect(latest, 'Expected at least one campaign to exist after brief submission').toBeTruthy();
  223 |     launchedCampaignId = latest.campaign_id;
  224 |     console.log(`Launched campaign: ${launchedCampaignId}`);
  225 |   });
  226 | 
  227 |   // ─────────────────────────────────────────────────────────────────────────
  228 |   // 4. Poll until terminal
  229 |   // ─────────────────────────────────────────────────────────────────────────
  230 |   test('4 · Campaign reaches a terminal status within 3 minutes', async () => {
  231 |     test.setTimeout(200_000);
  232 | 
  233 |     // Prefer the campaign launched by test 3; fall back to the pre-seeded one
  234 |     const idToPoll = launchedCampaignId || seededCampaignId;
  235 | 
  236 |     if (!idToPoll) {
  237 |       // Try latest from API as last resort
  238 |       const listRes = await fetch(`${API}/campaigns`, {
  239 |         headers: { Authorization: `Bearer ${accessToken}` },
  240 |       });
  241 |       const listBody = await listRes.json().catch(() => ({ campaigns: [] }));
  242 |       launchedCampaignId = (listBody.campaigns || [])[0]?.campaign_id || '';
  243 |     } else {
  244 |       launchedCampaignId = idToPoll;
  245 |     }
  246 | 
  247 |     expect(launchedCampaignId, 'No campaign ID to poll — tests 3 and seed both failed').toBeTruthy();
  248 | 
  249 |     const finalCampaign = await pollUntilTerminal(launchedCampaignId, accessToken);
  250 |     console.log(`Campaign ${launchedCampaignId} finished with status: ${finalCampaign.status}`);
  251 |     expect(TERMINAL.has(finalCampaign.status.toLowerCase())).toBe(true);
  252 |   });
  253 | 
  254 |   // ─────────────────────────────────────────────────────────────────────────
  255 |   // 5. Gallery view shows the campaign card
  256 |   // ─────────────────────────────────────────────────────────────────────────
  257 |   test('5 · Gallery shows the campaign card', async ({ page }) => {
  258 |     await injectAuth(page, accessToken, refreshToken);
  259 |     await page.goto('/gallery');
  260 | 
  261 |     // Page must load — verify the "Campaign Gallery" heading
  262 |     await expect(page.getByRole('heading', { name: /campaign gallery/i }).first()).toBeVisible({
  263 |       timeout: 15_000,
  264 |     });
  265 | 
  266 |     // Wait for data to load (spinner/refresh button disappears)
  267 |     await page.waitForTimeout(3_000);
  268 | 
  269 |     // Check if any campaign cards exist; if so, verify the launched/seeded one appears
  270 |     const cards = page.locator('article[role="button"]');
  271 |     const cardCount = await cards.count();
```