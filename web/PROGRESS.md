# Otto web: progress

Parts 1 and 2 are done. `npm run build`, `npm test` (94 tests) and backend `pytest -q` (518 passed,
5 skipped) pass. How to run it is in `README.md`; the chat's event → UI mapping is there too.

## Done

- **Backend (its own commit, f96ea64):** `GET /models` now gives each model a `description` and,
  when it's unavailable, a `hint` ("Unavailable right now. Try again later."). The built-in
  OpenRouter Free entry has the design's description. `OTTO_MODELS` entries may set
  `description`. Tests are updated, and `pytest -q` passes (492 passed, 5 skipped). The gateway
  running on :8000 needs a restart to serve these fields.
- **Scaffold:** Vite 8, React 19, TypeScript 6 with `strict` and `noUncheckedIndexedAccess`.
  - Tailwind v4 through `@tailwindcss/vite`.
  - The `@/*` path alias.
  - Vitest (jsdom) is configured in `vite.config.ts`.
- **Dependencies installed:** react-router, @tanstack/react-query, lucide-react, radix-ui
  (through the shadcn CLI), class-variance-authority, clsx, tailwind-merge, vitest, jsdom,
  Testing Library and msw.
- **`components.json`** is set up for shadcn. The generated files didn't fit our layout (they
  imported `cn` from the wrong path and needed a missing `Button`), so I deleted them. The
  components will be written by hand in shadcn's structure.
- **Logos:** copied exactly from `docs/design/assets` into `src/assets/logo/`.
- **`public/favicon.svg`:** the design's favicon plus a `<style>` block. The original sets no
  colours (classes `i` and `a` with no rules), so on its own it neither switches with the colour
  scheme nor shows the right colours. The style block makes it light/dark aware.

## Also done

- **Tokens and theme:** the tokens are in `src/index.css`. The theme (Light / Dark / System) is
  in `src/theme`, and `index.html` applies it before first paint.
- **The API client:** `src/api/client.ts`, with tests.
- **Pages:**
  - Sign in and sign up.
  - Forgot and reset password.
  - `/auth/callback`.
  - Onboarding (`/welcome`).
  - The shell: sidebar, drawer, row menu with Delete, and the profile menu.
  - Home with the composer.
  - The `/c/:id` placeholder.
  - Settings: Account, GitHub, Models, Usage and Appearance.
- **Tests (46):**
  - The auth client.
  - Mention parsing.
  - The model picker.
  - The composer.
  - Grouping sessions by date.
  - Formatting.
  - The sign-in guards.
- **Real-gateway check:** a Playwright smoke run against the gateway passed. It covered sign-up,
  onboarding skip, restoring the session on reload, sending a plain chat, the Settings pages,
  renaming, deleting a chat, sign-out, sign-in, and deleting the account.
- **Screenshots:** `npm run screenshots` captures the main screens, and they were compared with
  the mockup at 1440 and 390 in light and dark.

## Part 2: the chat (`/c/:id`)

- **Backend additions (their own commits, with tests):**
  - `ed689f0`: runner results carry what the UI shows:
    - `fs.replace`/`fs.write`: a unified `diff` (capped on a line boundary, with
      `diff_truncated`), `added`/`removed`, and `created` for `fs.write`
    - `git.push`: `base` and `diffstat` `{files, additions, deletions}`
    - `git.open_pr`: `title` and `base`
    - the brain strips these display-only fields before the model sees a tool result, so the
      model's input is unchanged
  - `cd14d8d`:
    - `GET /sessions/{id}` gives a repo session its `otto/<id>` work branch from the start
    - `POST /sessions/{id}/retry` runs a failed or interrupted turn again with no new message
      (a `retry` job, handled by the brain)
- **One pure reducer** (`src/chat/reduce.ts`) turns events into the view, with tests for every
  event kind. Infrastructure events are hidden.
- **Live updates** (`src/chat/live.ts`): events load over HTTP, then the WebSocket takes over with
  a fresh ticket, `after_seq` and backoff. Duplicates are dropped by seq, and "Reconnecting…" shows
  while the socket is down.
- **The chat column:**
  - user messages with repo chips; Otto's prose as light markdown
  - work blocks: live spinner and timer, collapsed to "N steps · 9 passed · 1m 48s" when done
  - PR cards, opened and updated
  - the error card with Retry, the limit card, the stopped note, and the mention nudge in plain
    chats
- **The composer in a chat:** Stop while Otto works; follow-ups between turns; 409 and 429 shown
  inline.
- **The workspace panel:**
  - Changes: numbered unified diffs and read slices, colored by Shiki (VS Code Light+ / Dark+,
    lazy-loaded)
  - Terminal: `$ cmd`, output, ✓/✗, and the "N passed" badge
  - a resizable side panel on desktop and a full-screen sheet on mobile
- **Real-backend run** (`scripts/e2e.mjs`): sign in, "@otto_test two tests are failing...", watch
  it work, follow-ups, Changes and Terminal, then screenshots at 1440 and 390 in light and dark.
  It opened Taufik041/otto_test#8.

## Differences from the design

- **"Help" is left out of the profile menu:** there's nowhere for it to go yet.
- **The "Check your inbox" screen says the link "expires in an hour":** the gateway's reset links
  last an hour, not the mockup's 30 minutes.
- **GitHub settings handles more than one installation:** with one, "Disconnect" sits beside "Add
  or remove repositories", as designed. With several, they're listed under "Installations", each
  with its own Disconnect. The gateway disconnects per installation, and its answer links to
  uninstalling on GitHub.
- **Settings › Usage shows no sandboxes:** the UI never shows sandbox internals, so the gateway's
  `active_sandboxes` and `POST /sessions/{id}/sandbox/stop` aren't used in `web/`.
- **The chat keeps its model:** in a chat, the composer shows the model as a label with no menu,
  because the gateway refuses a model change on follow-ups.
- **The model-failed row says "6 tries", not "6 tries over 40s":** the error event has the attempt
  count but not the time.
- **No "Using the warm sandbox" notice,** and no other sandbox notices: infrastructure events are
  hidden, as specified.
- **The Terminal has no `gh pr create` entry:** the PR is opened through the GitHub API, not a
  command, so there is none to show.
- **A read step has no quoted line under it** (the mockup quotes the relevant line): the events
  don't say which line mattered. It shows "lines a–b" instead.
- **A follow-up's message appears when it's sent,** before its own event arrives: the backend
  writes it only when the worker starts the turn. After a reload in that window, the turn shows
  "Setting up workspace…" without the message for a moment.
- **Things the design doesn't show, but the spec or API needed:**
  - Settings › Account has an editable Name row and "Sign out of all devices".
  - There's a `/reset-password` page for the emailed link.
  - Sign-up and sign-in check for empty fields inline, because their buttons are never disabled.

## Decisions

- **Helpers go in `src/utils/`, not `src/lib/`:** the root `.gitignore` ignores every `lib/`
  directory, so a `src/lib/` folder would be silently left out of commits.
- **shadcn/Radix where it fits:** the dropdown menus (sidebar row, profile) and dialogs (delete
  confirmation, change password). The composer's @ and model popovers are custom: on mobile they
  have to become bottom sheets, and the mention list is driven from the textarea's keyboard.
- **Session status dot:**
  - Plain chat: no dot.
  - provisioning, queued or running: amber, pulsing.
  - done: green.
  - failed or interrupted: red.
  - stopped or limited: gray.
- **A GitHub install ends on /settings/github,** which the backend hard-codes. An install started
  from onboarding sets a sessionStorage flag, and /settings/github sees it and sends you back to
  /welcome for the success state. No backend change is needed.
- **GitHub cancels:** the callback sends a cancel to `/?github_error=...`. Signed out, that goes to
  /login with a friendly message. Signed in, it shows a notice on home.
- **Sending needs text,** because `POST /sessions` requires a non-empty `message`. A repo chip on
  its own isn't enough.
