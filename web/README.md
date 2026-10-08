# Otto web

The browser app: sign-in, onboarding, chats, and Settings. It uses Vite, React, TypeScript,
Tailwind, shadcn/ui (Radix), React Router, TanStack Query, Vitest and MSW.

## Run it

You need Node 22 and the gateway on `http://localhost:8000` (see `../docs/dev.md`).

    cd web
    npm install
    npm run dev          # http://localhost:5173

`VITE_API_URL` sets the gateway's URL; it defaults to `http://localhost:8000`. The gateway's
`CORS_ORIGINS` must include the app's origin, and its `FRONTEND_URL` must be the app's URL, so
GitHub sends the browser back here. The defaults (`http://localhost:5173`) already match.

| Script | What it does |
|---|---|
| `npm run dev` | The dev server, with hot reload. |
| `npm run build` | Type-checks (`tsc -b`) and builds into `dist/`. |
| `npm test` | Vitest, once. `npm run test:watch` keeps it running. Tests mock the API with MSW and never touch the network. |
| `npm run dev:landing` | The landing page (`landing.html`, `src/landing/`) on `http://localhost:5174`; `/404` is its 404 page. |
| `npm run build:landing` | Type-checks and builds the landing page into `dist-landing/` (`index.html`, `404.html`, `assets/`). |
| `npm run preview` / `npm run preview:landing` | Serve the last build (`dist/` on :4173, `dist-landing/` on :4174) with production's routes, real 404s and headers (`vercel/site.mjs`). |
| `npm run vercel:app` / `npm run vercel:landing` | Vercel's build commands: build, then write `.vercel/output/` (Build Output API: files, routes, headers). See `../docs/deploy.md`. |
| `npm run screenshots` | Playwright screenshots of the main screens at 1440px and 390px, light and dark, into `screenshots/`. They show the design brief's sample data from a mocked API. Needs `npm run dev` running and `npx playwright install chromium` once. |

## The landing page

The site at otto.taufi.dev is a second build of this project (`vite.landing.config.ts`), so it
shows the app's own components.

- **Every section is from the design:**
  - the nav with the status pill
  - the two-tone hero, the replay window with the floating PR card, and drifting code fragments
  - the stack marquee
  - three steps and the bento (their vignettes are real components: the @ picker, a work block,
    the proposal and PR cards, the model menu, the workspace)
  - the architecture diagram, the final call to action, and the footer
- **The replay** (`src/landing/replay.ts`, `Replay.tsx`):
  - It plays the sample session (`src/fixtures/session.js`, shared with the screenshot script)
    through the app's reducer, as timed events in a ~35s loop, into the real `Thread` and
    `Workspace`.
  - The order: steps → 2 failed → the diff → 9 passed → Ready for review → a cursor clicks the
    real Create button → "Pull request opened #9".
  - `PrActionsContext` (`src/chat/prActions.ts`) gives the card a pretend create, so nothing
    calls a gateway.
  - It's inert (an illustration), and drawn at 1100×620, then scaled. On phones it's 800px
    wide, cropped by the screen, not shrunk.
  - With reduced motion it shows the final state, still.
- **The status pill** (`src/landing/status.ts`):
  - It asks `VITE_API_URL/health`, with a 2s timeout, every 60s. The gateway's
    `OTTO_LANDING_ORIGINS` must include the landing page's origin.
  - Three states:
    - **Live** (blue): up, workers online.
    - **Chat only** (amber): up, workers offline. The footer line reads "Chat is live ·
      sandboxes are offline right now". Get started still goes to the app.
    - **Offline** (grey): unreachable, or `paused`.
  - `VITE_STATUS_OVERRIDE=up|down` skips asking (`auto` by default).
  - Live and Chat only: "Get started" and "Log in" go to `VITE_APP_URL/login` (default
    `https://ottoci.taufi.dev`). Offline: they open the offline dialog.
- **The offline dialog** (`src/landing/OfflineDialog.tsx`): "Bring it back up" opens a short
  form (your email, a message, a hidden honeypot) that posts to `/api/wake`. "Book a live demo"
  opens `VITE_DEMO_BOOKING_URL` in a new tab (hidden when unset). If the email can't go (503,
  502, no network), it offers a `mailto:` with the same message instead.
- **`/api/wake`** (`vercel/wake.mjs`): a Vercel function in the landing project. It emails
  `OTTO_NOTIFY_TO` through Resend, with the visitor as the reply-to, and never emails the
  visitor. `npm run dev:landing` and `preview:landing` serve the same handler, but print the
  email instead of sending it. See `../docs/deploy.md`, "Environment variables".
- **Beta:** a Beta pill beside the wordmark (here, in the sign-in dialog and in the app's
  sidebar), "Free during beta" above the headline, and a footer line.
- **The theme** follows the system's light or dark, and the favicon follows it; the landing page
  has no switch.
- **Other settings:** `VITE_LINKEDIN_URL` sets the footer's LinkedIn link (hidden when unset).
  Put local values in `web/.env.local` (gitignored), e.g. `VITE_DEMO_BOOKING_URL`.
- **Screenshots:** with `npm run dev:landing` running, `node scripts/landing-screenshots.mjs`
  shoots the page (Live, Offline and its dialog, the menu, the replay's moments, reduced motion,
  the 404) at 1440 and 390, light and dark, into `screenshots/landing/`. `/health` is mocked.

## How it's put together

- **`src/api/client.ts`:** the API client and the signed-in state.
  - The access token lives only in memory and goes out as `Authorization: Bearer`.
  - Every request sends cookies (`credentials: "include"`), for the refresh cookie.
  - On load the app calls `POST /auth/refresh`.
  - A 401 refreshes once and retries the request once. A refresh the gateway refuses signs out.
  - Refreshes are single-flight: one promise per tab, plus `navigator.locks` across tabs.
  - The next refresh is scheduled about a minute before the token expires.
- **`src/api/index.ts`:** one function per endpoint.
- **`src/api/queries.ts`:** the TanStack Query hooks.
- **`src/index.css`:** the design tokens (copied from `docs/design/Otto v4.dc.html`) for light and
  dark, as CSS variables. Tailwind utilities map onto them (`bg-bg2`, `text-muted`,
  `border-line`, `bg-accent-bg`, ...).
  - The theme is `data-theme` on `<html>`.
  - The choice (Light / Dark / System, **Light by default**) is kept in `localStorage` as
    `otto.theme`, and `index.html` applies it before first paint.
  - The favicon (`public/favicon-{light,dark}.svg`, `-32.png`, `-180.png`) and `theme-color`
    follow the active theme, including the in-app toggle.
  - Blue is the brand, not the button: links, focus rings, the working dot and spinners, selected
    rows, the PR cards' left line and @repo chips. Buttons are black/white or outlined pills, with
    no hover transition.
- **`HEADER_HEIGHT`** (`src/components/layers.ts`): the chat's top bar and the workspace panel's
  header are both 56px, so their hairlines line up.
- **`GET /health`** (`useHealth`, every 30s): while the workers are offline, the composer says so,
  and a repo task (or a repo chat's follow-up) can't be sent. Plain chat still works. The notice
  (`src/composer/WorkersOffline.tsx`) has "Ask Taufik to bring it up" (`POST /wake-requests`,
  once an hour per user; then "Taufik has been notified.") and "Book a live demo"
  (`VITE_DEMO_BOOKING_URL`, hidden when unset).
- **`src/components/ui/`:** shadcn components (button, dropdown menu, dialog, field), restyled to
  the design.
- **`src/composer/`:** the composer. It has the `@` repo picker and the model picker; on phones
  both become bottom sheets. It also shows the inline cards for the daily limit, the
  active-session cap and an unavailable model.
- **`src/shell/`:** the sidebar (collapsible; a drawer on phones), the top bar, the profile menu
  and deleting a chat.
- **`src/pages/`:** the "Log in or sign up" dialog, password reset, `/auth/callback`, onboarding
  (`/welcome`), home, the chat page, Settings, the legal pages, `/request-access` and the 404.
- **`src/utils/`:** pure helpers with tests: mention parsing, grouping chats by day,
  formatting. (It isn't called `lib/`, because the repo's `.gitignore` ignores `lib/`.)

### GitHub round trips

The gateway sends the browser back from GitHub to one of two places:

- `/auth/callback`, after a sign-in or linking an account.
- `/settings/github`, after an install.

Before leaving, the app writes the page to come back to in `sessionStorage` (`otto.return`), and
those two pages send you on to it. That's how onboarding and the @ picker get you back where you
started. When you cancel on GitHub, the gateway redirects to `/?github_error=...`, and the app
explains it on /login (signed out) or on home (signed in).

### Log in or sign up

`/login` is one dialog (a bottom sheet on phones), email first (`src/pages/auth/SignIn.tsx`).
`/signup` and `/forgot-password` redirect to it.

1. **Email:** GitHub, an email, Continue. `POST /auth/email-status` says whether the email has an
   account. A bad email is "Enter a valid email."
2. **Welcome back:** the password, then `POST /auth/login`.
   - A 401 is "That password isn't right."
   - "Forgot password?" sends the link (`POST /auth/forgot`), then shows "Check your inbox"; the
     link expires in 1 hour. It's hidden when `GET /health` says `"password_reset": false`
     (production without `RESEND_API_KEY`).
3. **Create your account:** a name and a password, then `POST /auth/signup`.
   - The only rule is the gateway's: at least 8 characters. The meter's other advice is optional.
   - 403 `invite_only` opens the request-access form (`POST /access-requests`), then "Request sent".
   - 503 `paused`, or an unreachable gateway, shows "Otto is offline right now."

A GitHub sign-up the gateway refused comes back as `/auth/callback?error=invite_only|paused`, and
the dialog opens in that state. "Continue with Google" shows only with `VITE_GOOGLE_AUTH=1`, and
there's no Google sign-in behind it yet. `VITE_LANDING_URL` (default `https://otto.taufi.dev`) is
where Close, "Watch the demo" and the public pages' logo go.

### Public pages

- **Legal:** `/legal/terms`, `/legal/privacy` and `/legal/acceptable-use`.
  - The text is in `src/pages/legal/content.ts`.
  - "Last updated" is the build date (`__BUILD_DATE__`).
  - They're linked from the dialog, the profile menu, Settings and the public footer.
- **`/request-access`:** the invite-only form as a page.
- **The 404:** any unknown path.

### Onboarding

`/welcome` is offered after signing up, and after a GitHub sign-in that created a new account. It
has three steps, and the first two can be skipped:

1. Connect GitHub: `POST /auth/github/url` with `{mode: "link"}`.
2. Install on repositories: `POST /github/install-url`.
3. The "Connected. N repositories available." screen.

Once you finish or skip, it isn't offered again in this browser
(`localStorage` `otto.onboarded.<user id>`).

## The chat (`/c/:id`)

The chat page loads `GET /sessions/{id}` and `GET /sessions/{id}/events`, then follows
`WS /sessions/{id}/ws`:

- Each (re)connect takes a fresh ticket from `POST /sessions/{id}/ws-ticket` and passes
  `after_seq` = the last seq it has.
- A dropped socket reconnects with backoff (1s, 2s, 4s, 8s, then every 15s), and the page shows
  "Reconnecting…" meanwhile.
- A deleted session (close code 4404) ends it.

The code is in `src/chat/live.ts` and `src/chat/useSessionView.ts`.

Everything the page shows comes from one pure reducer, `src/chat/reduce.ts`, which folds the
session's events into a view model: messages, work blocks with steps, PR cards, files changed,
terminal entries and status. It ignores events it has already seen (by `seq`), and replays from
the start when an older event arrives late. Its tests (`reduce.test.ts`) cover every event kind.

### The sidebar's dots

A chat's dot is its `attention` from `GET /sessions`:

- **amber, pulsing softly:** `working` (steady when reduced motion is on)
- **green:** `done`, a turn that ended after you last saw the chat
- **red:** `failed`, the same for a failed or interrupted turn
- **none:** `null` (seen, stopped by you, or anything else)

While a chat is open and the tab is visible, what arrives is seen. `useSessionView` posts
`/sessions/{id}/seen` with the latest seq (debounced), clears the chat's row in the list at once,
and refetches the list only after that post. So a chat you're watching never gets a dot when it
finishes. A hidden tab posts when it becomes visible again. The list refetches on window focus,
and every 10s while any chat is `working`; otherwise it doesn't poll.

### Events → UI

| Event | Payload | What the chat shows |
|---|---|---|
| `session.created` | `{task, repo, model}` | The first user message, with its repo chip. A turn starts. |
| `session.model_changed` | `{from, to}` | A quiet divider before the message it came with ("Switched to GPT-4.1 mini"). The header's model label follows it. |
| `session.titled` | `{title, source}` | Not in the thread: the chat's title in the header and the sidebar updates. |
| `repo.attached` | `{repo}` | A plain chat becomes an agent chat. The turn that attached the repo shows it as a chip, and that turn and later ones get work blocks. |
| `session.status` | `{status}` | `provisioning`/`queued`/`running` mean live. Before any step, the block shows only "Setting up workspace…". `done` finishes the block. `failed`/`interrupted` show the error card. `stopped` shows "You stopped Otto…". `limited` stops the block. Work starting again after a final status is a follow-up (a new turn), or a retry if the turn had failed (the same block continues). |
| `llm.message` (system) | | Hidden. |
| `llm.message` (user) | `{message}` | A user message. The task's own echo is merged with the first one. |
| `llm.message` (assistant, with tool calls) | `{message}` | Prose. Before the block's first step it introduces the block ("On it…"); after that it's a muted note inside the block. |
| `llm.message` (assistant, no tool calls) | `{message}` | Otto's reply, as light markdown, after the block and before the proposal or PR card; its first paragraph gets Otto's mark again. A repo turn that ran nothing shows just the reply, with no empty block. |
| `llm.message` (tool) | `{message}` | Hidden; `bus.result` has the same, in full. |
| `bus.action` + `bus.result` | `{action_id, kind, payload}` + `{action_id, ok, payload}` | A step. See the table below. |
| `pr.proposed` | `{title, body, head, base, additions, deletions, files, tests}` | The "Ready for review" card after the reply (the latest proposal only), badged "Not on GitHub yet". It has "Create pull request" (`POST /sessions/{id}/pr`; a black pill with GitHub's mark, "Creating pull request…" with a spinner while it runs, a plain error inside the card if GitHub refuses) and "Not now" (`POST /sessions/{id}/pr/decline`). Both are disabled while Otto works. |
| `pr.declined` | `{}` | The proposal folds to a quiet line: "Pull request not created · Create pull request". |
| `pr.opened` | `{number, html_url}` | The PR the user opened: the proposal's card becomes the PR card ("Pull request opened #N", badged "Open", with "View on GitHub" and "See changes ›"). |
| `pr.updated` | `{number, url, additions, deletions, files}` | A later turn's push updated the open PR: the PR card again, "Pull request updated", badged "Updated", with the new counts. |
| `usage.limit_reached` | `{used, limit, resets_at}` | The usage-limit card. |
| `error` | `{stage, step?, message}` | The error card with Retry (`POST /sessions/{id}/retry`), titled by what failed: `llm` → "Something went wrong." ("Otto stopped after N steps…"; the block ends with a red "No response" row); `model` (a provider error no wait fixes) with `reason` `quota` → "This model's provider is out of credit." ("{model} can't take more requests right now…", and the block's red row names the model), `auth` → "This model isn't set up correctly. Try another model.", `model` → "This model isn't available. Try another model.", each with a model picker beside Retry (`POST /sessions/{id}/retry {model}`); `create_sandbox`/`sandbox`/`enqueue` → "Otto couldn't set up the workspace."; `finish` with `step` `git.commit` → "Otto couldn't commit the changes.", `git.push` → "Otto couldn't push to GitHub.", `git.open_pr` → "Otto couldn't open the pull request."; anything else, or a failed turn with no error event → "Something went wrong." `destroy_sandbox`: hidden. The error's message is never shown. |
| `llm.usage`, `llm.key_rotated` | | Hidden (infrastructure). |
| `sandbox.reused`, `sandbox.recreated` | | Hidden (infrastructure). |
| anything else | | Ignored. |

| Action kind | Step | Result | Workspace |
|---|---|---|---|
| `shell.exec` | Ran `cmd` | pytest's summary ("2 failed, 7 passed", red; "9 passed", green), else `exit N` on failure | Terminal: `$ cmd`, output, ✓/✗, and a "9 passed" badge |
| `code.search` | Searched `pattern` | "N matches", with the first `file:line`s under it | Terminal: `$ rg -n -- pattern` |
| `fs.read` | Read `path` | "lines a–b" | Changes: Read, as a line-numbered slice |
| `fs.replace` | Edited `path` | +a −d | Changes: Edited, a numbered unified diff (from the result's `diff`) |
| `fs.write` | Created / Wrote `path` | +a −d | Changes: Created or Edited, with a diff |
| `git.status`, `git.diff` | Checked git status / Reviewed the diff | | Terminal |
| `git.commit` | Committed `message`; with the push that follows: Committed and pushed `branch` | | Terminal: `$ git add -A && git commit -m …` |
| `git.push` | Pushed `branch`, or Pushed to pull request `#n` once there's a PR | | Terminal: `$ git push -u origin branch` |
| `git.open_pr` | Opened pull request `#n` (older sessions only: Otto no longer opens PRs) | | Not in the Terminal: it's an API call, not a command |

A failed action shows red, with "failed" and its first error line. An action with no result when
the turn ended shows "Stopped".

**Pull requests are the user's call.** Otto commits and pushes `otto/<id>`, and its turn ends with a
proposal (`pr.proposed`). The "Ready for review" card (`src/chat/ProposalCard.tsx`) is in the PR
card's family:

- the proposal's title, `repo · otto/<id> → base`, `+additions −deletions`, the file count, and
  "N tests passed" when the last test run passed
- **Create pull request**, the primary button: it shows a spinner and is disabled while it runs,
  and GitHub's refusal shows under the buttons
- **Not now**, the secondary button
- both are disabled while Otto works, with "Otto is working…"; on phones they stack full-width

Once the PR is open, the card is the PR card: title, `#number`, repo, branch → base, the counts and
"View on GitHub". A newer proposal replaces an older one, and a later push to the open PR shows
the PR card again as "Pull request updated".

The diff, its line counts, `diffstat`, `base` and `title` are fields the runner adds to its
results for the UI. The brain leaves them out of what the model sees.
