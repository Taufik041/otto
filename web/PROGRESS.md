# Otto web: Part 1 progress

Part 1 is done. `npm run build`, `npm test` and backend `pytest -q` pass. How to run it is in `README.md`.

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

## Next (Part 2)

- The conversation at `/c/:id`:
  - Events over the WebSocket (`POST /sessions/{id}/ws-ticket`).
  - Work blocks and the PR card.
  - Follow-ups with `POST /sessions/{id}/messages`.
  - Stop and Rename in the "⋯" menu.
- The workspace panel: Changes and Terminal.

## Differences from the design

- **"Help" is left out of the profile menu:** there's nowhere for it to go yet.
- **The "Check your inbox" screen says the link "expires in an hour":** the gateway's reset links
  last an hour, not the mockup's 30 minutes.
- **GitHub settings handles more than one installation:** with one, "Disconnect" sits beside "Add
  or remove repositories", as designed. With several, they're listed under "Installations", each
  with its own Disconnect. The gateway disconnects per installation, and its answer links to
  uninstalling on GitHub.
- **Things the design doesn't show, but the spec or API needed:**
  - Settings › Account has an editable Name row and "Sign out of all devices".
  - Settings › Usage lists active sandboxes with Stop.
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
