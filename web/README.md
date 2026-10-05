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
| `npm run screenshots` | Playwright screenshots of the main screens at 1440px and 390px, light and dark, into `screenshots/`. They show the design brief's sample data from a mocked API. Needs `npm run dev` running and `npx playwright install chromium` once. |

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
- **`src/index.css`:** the design tokens (copied from `docs/design/Otto v3.dc.html`) for light and
  dark, as CSS variables. Tailwind utilities map onto them (`bg-bg2`, `text-muted`,
  `border-line`, `bg-accent-bg`, ...). The theme is `data-theme` on `<html>`. The choice
  (Light / Dark / System) is kept in `localStorage` as `otto.theme`, and `index.html` applies it
  before first paint.
- **`src/components/ui/`:** shadcn components (button, dropdown menu, dialog, field), restyled to
  the design.
- **`src/composer/`:** the composer. It has the `@` repo picker and the model picker; on phones
  both become bottom sheets. It also shows the inline cards for the daily limit, the
  active-session cap and an unavailable model.
- **`src/shell/`:** the sidebar (collapsible; a drawer on phones), the top bar, the profile menu
  and deleting a chat.
- **`src/pages/`:** sign-in and sign-up, password reset, `/auth/callback`, onboarding
  (`/welcome`), home, the chat page and Settings.
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
| `llm.message` (assistant, no tool calls) | `{message}` | Otto's reply, as light markdown, after the block and PR card. |
| `llm.message` (tool) | `{message}` | Hidden; `bus.result` has the same, in full. |
| `bus.action` + `bus.result` | `{action_id, kind, payload}` + `{action_id, ok, payload}` | A step. See the table below. |
| `pr.proposed` | `{title, body, head, base, additions, deletions, files, tests}` | The "Ready for review" card after the block (the latest proposal only): "Create pull request" (`POST /sessions/{id}/pr`) and "Not now" (`POST /sessions/{id}/pr/decline`), both disabled while Otto works. |
| `pr.declined` | `{}` | The proposal folds to a quiet line: "Pull request not created · Create pull request". |
| `pr.opened` | `{number, html_url}` | The PR the user opened: the proposal's card becomes the PR card ("Pull request opened"). |
| `pr.updated` | `{number, url, additions, deletions, files}` | A later turn's push updated the open PR: the PR card again, "Pull request updated", with the new counts. |
| `usage.limit_reached` | `{used, limit, resets_at}` | The usage-limit card. |
| `error` | `{stage, step?, message}` | The error card with Retry (`POST /sessions/{id}/retry`), titled by what failed: `llm` → "Otto couldn't finish." (the model didn't respond after N tries); `model` (a provider error no wait fixes) with `reason` `quota` → "This model's provider is out of credit. Switch models and retry.", `auth` → "This model isn't set up correctly. Try another model.", `model` → "This model isn't available. Try another model.", each with a model picker beside Retry (`POST /sessions/{id}/retry {model}`); `create_sandbox`/`sandbox`/`enqueue` → "Otto couldn't set up the workspace."; `finish` with `step` `git.commit` → "Otto couldn't commit the changes.", `git.push` → "Otto couldn't push to GitHub.", `git.open_pr` → "Otto couldn't open the pull request."; anything else, or a failed turn with no error event → "Something went wrong." `destroy_sandbox`: hidden. The error's message is never shown. |
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
