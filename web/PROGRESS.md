# Otto web: Part 1 progress

Work in progress. `npm run build` and `npm test` pass from "web: tokens, theme, API client" on.

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

## Next

1. **`src/index.css`:** the mockup's tokens for light and dark (`--bg`, `--bg2`, `--card`,
   `--text`, `--muted`, `--line`, `--hair`, `--accent`, the status colours, etc.), mapped through
   Tailwind `@theme inline`. Add the keyframes (rise, fade, pop, sheet, spin, pulse) and the
   reduced-motion rule. In `index.html`, add a script that applies the theme before first paint.
2. **Theme:** Light / Dark / System, saved in localStorage as `otto.theme`, and applied as
   `data-theme` on `<html>`.
3. **`src/api/`:**
   - **The auth client:** a factory, so it can be tested.
     - The access token lives in memory only.
     - Refresh is single-flight: one in-flight promise, plus `navigator.locks` across tabs.
     - A 401 refreshes once and retries once. If the token changed while the request was in
       flight, it just retries.
     - It refreshes proactively about 60s before expiry.
     - A failed refresh signs you out. A network error does not.
   - **API types and TanStack Query hooks:** me, models, repos, sessions, usage, github.
4. **Pages:**
   - Auth: /login, /signup, /forgot-password, /reset-password and /auth/callback.
   - /welcome, the onboarding flow:
     - Step 1, link GitHub: `POST /auth/github/url` with mode `"link"`.
     - Step 2, install: `POST /github/install-url`.
     - Step 3, done: "Connected. N repositories available."
   - The shell: sidebar, drawer, row menu with Delete, and the profile menu.
   - Home: the composer with the @ picker and the model picker.
   - `/c/:id` as a placeholder.
   - Settings: account, github, models, usage and appearance.
5. **Tests:**
   - The auth client.
   - Mention parsing.
   - The model picker's disabled state.
   - Grouping sessions by date.
6. **Last:** README, docs/dev.md, Playwright screenshots at 1440 and 390 in light and dark, and
   fixing whatever differs from the mockup.

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
- **"Help" in the profile menu:** the design has it, but there's nowhere for it to go yet. I plan
  to leave it out and list it in the summary as a difference.
- **Sending needs text,** because `POST /sessions` requires a non-empty `message`. A repo chip on
  its own isn't enough.
