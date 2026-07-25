# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: campaign_e2e.spec.js >> OmniBrand Studio — Campaign E2E >> 3 · Submit brief, confirm, and launch campaign
- Location: tests\e2e\campaign_e2e.spec.js:183:3

# Error details

```
Test timeout of 200000ms exceeded.
```

```
Error: locator.fill: Test timeout of 200000ms exceeded.
Call log:
  - waiting for getByPlaceholder(/type a message/i).or(locator('textarea').last()).or(locator('input[type="text"]').last())

```

# Page snapshot

```yaml
- generic [active] [ref=f2e1]:
  - generic [ref=f2e3]:
    - link "Skip to main content" [ref=f2e4] [cursor=pointer]:
      - /url: "#main-content"
    - complementary "Sidebar" [ref=f2e5]:
      - generic [ref=f2e6]:
        - link "OmniBrand Studio — home" [ref=f2e7] [cursor=pointer]:
          - /url: /
          - generic [ref=f2e12]:
            - text: OmniBrand
            - generic [ref=f2e13]: Studio
        - button "Collapse sidebar" [ref=f2e14]
      - generic [ref=f2e19]:
        - navigation "Primary" [ref=f2e20]:
          - generic [ref=f2e21]:
            - heading "Create" [level=2] [ref=f2e22]
            - list [ref=f2e23]:
              - listitem [ref=f2e24]:
                - link "Workspace" [ref=f2e25] [cursor=pointer]:
                  - /url: /app
              - listitem [ref=f2e31]:
                - link "Campaigns" [ref=f2e32] [cursor=pointer]:
                  - /url: /gallery
          - generic [ref=f2e39]:
            - heading "Manage" [level=2] [ref=f2e40]
            - list [ref=f2e41]:
              - listitem [ref=f2e42]:
                - link "Admin Panel" [ref=f2e43] [cursor=pointer]:
                  - /url: /admin
        - button "Made with by Adobe Team" [ref=f2e49] [cursor=pointer]:
          - text: Made withby
          - generic [ref=f2e52]: Adobe Team
    - generic [ref=f2e53]:
      - banner [ref=f2e54]:
        - heading "Campaign Studio" [level=1] [ref=f2e55]
        - generic [ref=f2e56]:
          - switch "Switch to dark mode" [ref=f2e57]
          - button "Notifications, 2 unread" [ref=f2e68]:
            - generic [ref=f2e72]: "2"
          - generic [ref=f2e75]:
            - button "U User" [ref=f2e76]:
              - generic [ref=f2e77]: U
              - generic [ref=f2e78]: User
            - button "Log out" [ref=f2e79]
      - main [ref=f2e83]:
        - generic [ref=f2e84]:
          - generic [ref=f2e85]:
            - generic [ref=f2e86]:
              - paragraph [ref=f2e87]: Workspace
              - heading "Campaign Studio" [level=1] [ref=f2e88]
              - paragraph [ref=f2e89]: Chat to build a brief, then watch the pipeline run in real time.
            - generic [ref=f2e91]:
              - generic "Chat connected" [ref=f2e92]: Chat
              - button "New conversation" [ref=f2e97]
          - generic [ref=f2e99]:
            - generic [ref=f2e100]:
              - generic [ref=f2e101]:
                - heading "Conversations" [level=2] [ref=f2e102]
                - button "Refresh conversations" [ref=f2e103]
              - generic [ref=f2e109]:
                - button "f2f36d54-b90… processing · 5m ago" [ref=f2e110]:
                  - paragraph [ref=f2e113]: f2f36d54-b90…
                  - paragraph [ref=f2e114]:
                    - generic [ref=f2e115]: processing
                    - generic [ref=f2e116]: · 5m ago
                - button "4996ea8d-39e… collecting · 2h ago" [ref=f2e117]:
                  - paragraph [ref=f2e120]: 4996ea8d-39e…
                  - paragraph [ref=f2e121]:
                    - generic [ref=f2e122]: collecting
                    - generic [ref=f2e123]: · 2h ago
                - button "d231a031-215… collecting · 8h ago" [ref=f2e124]:
                  - paragraph [ref=f2e127]: d231a031-215…
                  - paragraph [ref=f2e128]:
                    - generic [ref=f2e129]: collecting
                    - generic [ref=f2e130]: · 8h ago
                - button "824755ff-a85… collecting · 9h ago" [ref=f2e131]:
                  - paragraph [ref=f2e134]: 824755ff-a85…
                  - paragraph [ref=f2e135]:
                    - generic [ref=f2e136]: collecting
                    - generic [ref=f2e137]: · 9h ago
                - button "d47a2d95-517… collecting · 9h ago" [ref=f2e138]:
                  - paragraph [ref=f2e141]: d47a2d95-517…
                  - paragraph [ref=f2e142]:
                    - generic [ref=f2e143]: collecting
                    - generic [ref=f2e144]: · 9h ago
                - button "828b3802-a6c… collecting · 1d ago" [ref=f2e145]:
                  - paragraph [ref=f2e148]: 828b3802-a6c…
                  - paragraph [ref=f2e149]:
                    - generic [ref=f2e150]: collecting
                    - generic [ref=f2e151]: · 1d ago
                - button "8225b7c8-6e6… processing · 1d ago" [ref=f2e152]:
                  - paragraph [ref=f2e155]: 8225b7c8-6e6…
                  - paragraph [ref=f2e156]:
                    - generic [ref=f2e157]: processing
                    - generic [ref=f2e158]: · 1d ago
                - button "683c4771-474… collecting · 1d ago" [ref=f2e159]:
                  - paragraph [ref=f2e162]: 683c4771-474…
                  - paragraph [ref=f2e163]:
                    - generic [ref=f2e164]: collecting
                    - generic [ref=f2e165]: · 1d ago
                - button "4d3911a3-770… collecting · 1d ago" [ref=f2e166]:
                  - paragraph [ref=f2e169]: 4d3911a3-770…
                  - paragraph [ref=f2e170]:
                    - generic [ref=f2e171]: collecting
                    - generic [ref=f2e172]: · 1d ago
                - button "cd6e52e8-1e6… processing · 1d ago" [ref=f2e173]:
                  - paragraph [ref=f2e176]: cd6e52e8-1e6…
                  - paragraph [ref=f2e177]:
                    - generic [ref=f2e178]: processing
                    - generic [ref=f2e179]: · 1d ago
                - button "ab42f77a-805… collecting · 1d ago" [ref=f2e180]:
                  - paragraph [ref=f2e183]: ab42f77a-805…
                  - paragraph [ref=f2e184]:
                    - generic [ref=f2e185]: collecting
                    - generic [ref=f2e186]: · 1d ago
                - button "fd3579d4-1df… collecting · 1d ago" [ref=f2e187]:
                  - paragraph [ref=f2e190]: fd3579d4-1df…
                  - paragraph [ref=f2e191]:
                    - generic [ref=f2e192]: collecting
                    - generic [ref=f2e193]: · 1d ago
            - generic [ref=f2e194]:
              - generic [ref=f2e195]:
                - generic [ref=f2e201]:
                  - heading "Campaign Studio" [level=2] [ref=f2e202]
                  - paragraph [ref=f2e203]: f2f36d54-b90d-49e2-921f-97df7822cd70
                - generic [ref=f2e204]: campaign discovery
              - generic [ref=f2e206]: Campaign cost —·Tokens —
              - paragraph [ref=f2e214]: Resumed conversation f2f36d54-b90d-49e2-921f-97df7822cd70. Continue the brief or run campaign when ready.
              - generic [ref=f2e215]:
                - generic [ref=f2e216]:
                  - button "What is the current campaign status?" [ref=f2e217]
                  - button "What happened in the last step?" [ref=f2e218]
                  - button "Show outputs from content_generator" [ref=f2e219]
                - generic [ref=f2e220]:
                  - textbox "Describe your campaign..." [ref=f2e221]
                  - button "Send message" [disabled] [ref=f2e222]
            - generic [ref=f2e226]:
              - generic [ref=f2e227]:
                - button "Brief" [ref=f2e228]
                - button "Pipeline" [ref=f2e232]
              - generic [ref=f2e235]:
                - generic [ref=f2e236]:
                  - generic [ref=f2e237]:
                    - generic [ref=f2e238]: 5 of 5 complete
                    - generic [ref=f2e239]: 100%
                  - list [ref=f2e242]:
                    - listitem [ref=f2e243]:
                      - generic [ref=f2e248]:
                        - paragraph [ref=f2e250]: Objective
                        - paragraph [ref=f2e251]: drive qualified demo requests
                    - listitem [ref=f2e252]:
                      - generic [ref=f2e257]:
                        - paragraph [ref=f2e259]: Channels
                        - generic [ref=f2e260]:
                          - generic [ref=f2e261]: instagram
                          - generic [ref=f2e262]: x
                          - generic [ref=f2e263]: email
                    - listitem [ref=f2e264]:
                      - generic [ref=f2e269]:
                        - paragraph [ref=f2e271]: Locales
                        - generic [ref=f2e272]:
                          - generic [ref=f2e273]: en-us
                          - generic [ref=f2e274]: es-es
                    - listitem [ref=f2e275]:
                      - generic [ref=f2e280]:
                        - paragraph [ref=f2e282]: Audience segments
                        - generic [ref=f2e283]:
                          - generic [ref=f2e284]: Young adults aged 20-30 (Gen Z and Millennials who value experiences
                          - generic [ref=f2e285]: exploration
                          - generic [ref=f2e286]: social proof
                          - generic [ref=f2e287]: and breaking their daily routine)
                    - listitem [ref=f2e288]:
                      - generic [ref=f2e292]:
                        - paragraph [ref=f2e294]: Token budget
                        - paragraph [ref=f2e295]: 5,000 tokens
                - paragraph [ref=f2e300]: When every field is complete, send “run campaign” to enqueue execution.
  - generic [ref=f2e303]:
    - button [ref=f2e304]
    - button [ref=f2e310]
    - button [ref=f2e314]
    - button [ref=f2e322]
```

# Test source

```ts
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
  169 |     // Click "New conversation" to ensure we start from an empty state
  170 |     const newConvBtn = page.getByRole('button', { name: /new conversation/i });
  171 |     if (await newConvBtn.isVisible({ timeout: 5_000 }).catch(() => false)) {
  172 |       await newConvBtn.click();
  173 |       // Wait for the creating state to resolve
  174 |       await expect(newConvBtn).not.toHaveText(/creating/i, { timeout: 10_000 }).catch(() => {});
  175 |     }
  176 | 
  177 |     // The chip is only rendered when the conversation is empty (canChat && messages.length === 0)
  178 |     const chip = page.getByRole('button', { name: /show me an example brief/i });
  179 |     await expect(chip).toBeVisible({ timeout: 15_000 });
  180 |     await chip.click();
  181 | 
  182 |     // After clicking the chip, sendPrompt fires — expect a user message bubble to appear
  183 |     await expect(
  184 |       page.locator('[class*="message"], .message-bubble').first(),
  185 |     ).toBeVisible({ timeout: 20_000 });
  186 |     console.log('Sample brief chip fired successfully');
  187 |   });
  188 | 
  189 |   // ─────────────────────────────────────────────────────────────────────────
  190 |   // 3. Submit brief and launch campaign
  191 |   // ─────────────────────────────────────────────────────────────────────────
  192 |   test('3 · Submit brief, confirm, and launch campaign', async ({ page }) => {
  193 |     test.setTimeout(200_000);
  194 |     await injectAuth(page, accessToken, refreshToken);
  195 |     await page.goto('/app');
  196 | 
> 197 |     await expect(page.getByRole('heading', { name: /campaign studio/i }).first()).toBeVisible({
      |                 ^ Error: locator.fill: Test timeout of 200000ms exceeded.
  198 |       timeout: 15_000,
  199 |     });
  200 | 
  201 |     // Click "New conversation" to get a fresh empty chat
  202 |     const newConvBtn = page.getByRole('button', { name: /new conversation/i });
  203 |     if (await newConvBtn.isVisible({ timeout: 5_000 }).catch(() => false)) {
  204 |       await newConvBtn.click();
  205 |       await expect(newConvBtn).not.toHaveText(/creating/i, { timeout: 10_000 }).catch(() => {});
  206 |     }
  207 | 
  208 |     // Type the brief in the chat input
  209 |     const input = page
  210 |       .getByPlaceholder(/type a message/i)
  211 |       .or(page.locator('textarea').last())
  212 |       .or(page.locator('input[type="text"]').last());
  213 |     await input.fill(SAMPLE_BRIEF);
  214 |     await input.press('Enter');
  215 | 
  216 |     // Wait for assistant to respond
  217 |     await expect(page.locator('.message-bubble, [class*="message"]').last()).toBeVisible({
  218 |       timeout: 45_000,
  219 |     });
  220 | 
  221 |     // If a launch/confirm button appears, click it; otherwise type "yes"
  222 |     const launchBtn = page.getByRole('button', { name: /launch|confirm|start campaign/i });
  223 |     if (await launchBtn.isVisible({ timeout: 8_000 }).catch(() => false)) {
  224 |       await launchBtn.click();
  225 |     } else {
  226 |       // The copilot may have auto-confirmed; send an explicit confirmation
  227 |       await input.fill('Yes, launch it.');
  228 |       await input.press('Enter');
  229 |     }
  230 | 
  231 |     // Wait up to 60s for a campaign to appear in the API list
  232 |     await page.waitForTimeout(5_000);
  233 |     const listRes = await fetch(`${API}/campaigns`, {
  234 |       headers: { Authorization: `Bearer ${accessToken}` },
  235 |     });
  236 |     const listBody = await listRes.json().catch(() => ({ campaigns: [] }));
  237 |     const latest = (listBody.campaigns || [])[0];
  238 |     expect(latest, 'Expected at least one campaign to exist after brief submission').toBeTruthy();
  239 |     launchedCampaignId = latest.campaign_id;
  240 |     console.log(`Launched campaign: ${launchedCampaignId}`);
  241 |   });
  242 | 
  243 |   // ─────────────────────────────────────────────────────────────────────────
  244 |   // 4. Poll until terminal
  245 |   // ─────────────────────────────────────────────────────────────────────────
  246 |   test('4 · Campaign reaches a terminal status within 3 minutes', async () => {
  247 |     test.setTimeout(200_000);
  248 | 
  249 |     // Prefer the campaign launched by test 3; fall back to the pre-seeded one
  250 |     const idToPoll = launchedCampaignId || seededCampaignId;
  251 | 
  252 |     if (!idToPoll) {
  253 |       // Try latest from API as last resort
  254 |       const listRes = await fetch(`${API}/campaigns`, {
  255 |         headers: { Authorization: `Bearer ${accessToken}` },
  256 |       });
  257 |       const listBody = await listRes.json().catch(() => ({ campaigns: [] }));
  258 |       launchedCampaignId = (listBody.campaigns || [])[0]?.campaign_id || '';
  259 |     } else {
  260 |       launchedCampaignId = idToPoll;
  261 |     }
  262 | 
  263 |     expect(launchedCampaignId, 'No campaign ID to poll — tests 3 and seed both failed').toBeTruthy();
  264 | 
  265 |     const finalCampaign = await pollUntilTerminal(launchedCampaignId, accessToken);
  266 |     console.log(`Campaign ${launchedCampaignId} finished with status: ${finalCampaign.status}`);
  267 |     expect(TERMINAL.has(finalCampaign.status.toLowerCase())).toBe(true);
  268 |   });
  269 | 
  270 |   // ─────────────────────────────────────────────────────────────────────────
  271 |   // 5. Gallery view shows the campaign card
  272 |   // ─────────────────────────────────────────────────────────────────────────
  273 |   test('5 · Gallery shows the campaign card', async ({ page }) => {
  274 |     await injectAuth(page, accessToken, refreshToken);
  275 |     await page.goto('/gallery');
  276 | 
  277 |     // Page must load — verify the "Campaign Gallery" heading
  278 |     await expect(page.getByRole('heading', { name: /campaign gallery/i }).first()).toBeVisible({
  279 |       timeout: 15_000,
  280 |     });
  281 | 
  282 |     // Wait for data to load (spinner/refresh button disappears)
  283 |     await page.waitForTimeout(3_000);
  284 | 
  285 |     // Check if any campaign cards exist; if so, verify the launched/seeded one appears
  286 |     const cards = page.locator('article[role="button"]');
  287 |     const cardCount = await cards.count();
  288 |     console.log(`Gallery card count: ${cardCount}`);
  289 | 
  290 |     if (cardCount > 0) {
  291 |       // Verify the first card is visible
  292 |       await expect(cards.first()).toBeVisible({ timeout: 5_000 });
  293 | 
  294 |       // Try to match on short ID of launched or seeded campaign
  295 |       const shortId = (launchedCampaignId || seededCampaignId)?.slice(0, 8) ?? '';
  296 |       if (shortId) {
  297 |         const idMatch = page.locator(`text=/${shortId}/i`).first();
```