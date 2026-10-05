# Otto: UI design brief (v3, "works like Claude, looks like Apple")

> This replaces v2. Drop the form-based home screen and the permanent three-panel layout from v2.
> Otto is now a **chat app**: it works like Claude and looks like an Apple product page.

**What Otto is:** an autonomous coding agent. You chat with it. When you mention a GitHub repo with
`@`, it works on that repo in an isolated sandbox: it runs commands, edits files and tests, and
sends back a pull request. Without a repo it's a normal assistant.

**Future scope, which the design must leave room for:** "chat to website". You describe a site, and
Otto creates the repo and builds it. So chat is the core, not a task form.

**Source of truth for visuals:** the attached `apple-vibes-design-guide.md`.
**Logo:** option 1a, "The loop". SVG files are attached; use them exactly as given.

Design every screen at **desktop width (1440px) and mobile width (390px)**. Mobile is a primary
target, not an afterthought.

---

## 1. Feeling

- **Interaction model: Claude.** A calm sidebar, a single conversation, and a big friendly composer.
  The agent's work appears as tidy, collapsible steps inside the conversation, and the details open
  in a side panel on demand.
- **Visual language: Apple.** Near-black on near-white, generous whitespace, one accent color
  (`#0071e3` light / `#2997ff` dark), SF-style system type, semibold headings, soft rounded cards
  and a frosted translucent top bar. Restraint everywhere.
- **The one bold area is code content:** terminal output and diffs, in monospace and syntax color.
  The satisfying moments are tests going green and the PR card arriving.
- Keep it quiet. No gradients, no glow, no dashboard clutter. If an element doesn't help the user
  talk to Otto or see its work, remove it.

## 2. Themes and tokens

Build everything on CSS variables. Both themes are first-class, with a Light / Dark / System toggle.

- **Light:**
  - background `#ffffff`, secondary background `#f5f5f7`
  - text `#1d1d1f`, muted text `#6e6e73`
  - hairlines `#d2d2d7`, accent `#0071e3`
- **Dark:**
  - background `#000000`, secondary background `#1d1d1f`
  - text `#f5f5f7`, muted text `#86868b`
  - hairlines `#424245`, accent `#2997ff`
- **Status colors** (muted signals, never decoration): green = success, amber = working,
  red = failed, gray = stopped or asleep.

Stack: ShadCN/ui + Tailwind, restyled to this system rather than the defaults.

## 3. Logo usage

- **Sidebar header:** the lockup (loop mark plus the "otto" wordmark), about 22px tall.
- **Collapsed sidebar and mobile top bar:** the mark only.
- **Favicon:** `favicon.svg`, which switches between light and dark on its own.
- **Otto's avatar** beside its messages: the mark, small (20px). While Otto is working, the blue
  dot can travel slowly around the loop; it's the only animated brand element.
- **Auth screens:** the mark, large, centered.

---

## 4. Screens

### 4.1 Sign in / sign up
- A centered card on the secondary background: the logo mark, then a headline.
  - Sign in: "Welcome back."
  - Sign up: "Create your Otto account."
- **"Continue with GitHub"**: the primary button, in near-black style with the GitHub icon.
- A divider ("or"), then an **email + password** form. Sign up also asks for a name. Include a
  **"Forgot password?"** link and a switch between sign in and sign up.
- Show inline validation and error states: wrong password, email already registered, weak password.
- **Forgot password screen:** enter an email, then a "Check your inbox" confirmation.

### 4.2 Onboarding: connect GitHub (first run)
- One screen: "Connect GitHub so Otto can work on your repos." Explain in one line that Otto only
  sees the repos you choose.
- Primary action: **"Connect GitHub"**. It goes to GitHub, where the user picks repos, and returns.
- Secondary action: **"Skip for now"**. Plain chat still works; `@` will show a connect prompt.
- A success state: "Connected. 3 repositories available." with the repo names listed.

### 4.3 App shell
- **Left sidebar** (collapsible on desktop, a drawer on mobile):
  - At the top: the lockup, then a **"New chat"** button and a search field for chats.
  - **Recent chats**, grouped by Today / Yesterday / Previous 7 days / Older. Each row shows the
    chat title (auto-named from the first message), a tiny status dot (working, done, failed, or
    none for plain chat), and the repo in muted text when there is one.
  - At the bottom: the **profile button** (avatar and name). Its menu contains Settings, Usage,
    Theme (Light / Dark / System), Help and Sign out.
- **Main area:** the conversation. A thin top bar holds the chat title, the repo chip, the model
  label and a "⋯" menu (Rename, Stop, Delete). The composer stays pinned to the bottom.

### 4.4 Empty state (new chat)
- A centered greeting such as "What should we build today, Taufik?" and a large composer.
- 3–4 quiet **suggestion chips** that fill the composer when tapped:
  - "@otto_test fix the failing tests"
  - "@otto_test add tests for Order"
  - "Explain how the pricing works in @otto_test"
  - "What can you do?"

### 4.5 The composer (the most important component)
- A multi-line input with rounded corners that grows with its content.
- **`@` mention.** Typing `@` opens a popover listing the user's connected repos:
  - each row shows the owner/repo name, a lock icon if the repo is private, and "updated 2h ago"
  - typing filters the list; arrow keys and Enter select
  - the footer holds "Manage repositories", which links to the GitHub settings
  - the chosen repo becomes an inline **chip** inside the message
  - if GitHub isn't connected, the popover shows "Connect GitHub to mention repos" and a button
  - on mobile, the popover becomes a **bottom sheet**
- **Model picker** (bottom-left of the composer, like Claude's). A compact button showing the current
  model opens a menu grouped by provider, **OpenRouter** and **OpenAI**. Each option shows the name
  and a one-line description. Unavailable models are disabled with a hint. The default model is
  marked. On mobile this is a bottom sheet.
- **Send button** (bottom-right). While Otto is working it becomes a **Stop** button.
- Below the composer, in muted text, a hint that changes with context:
  - "Otto works in a sandbox and proposes a pull request for you to review."
  - "Otto is working… you can keep reading or stop it."

### 4.6 Conversation
- **User messages:** right-aligned, in a subtle rounded bubble on the secondary background. The
  repo chip is rendered inline.
- **Otto's messages:** left-aligned, no bubble, readable prose with light markdown. Code blocks are
  in monospace. The small loop mark is Otto's avatar.
- **Work block.** When Otto works on a repo, a card appears in the thread:
  - header: "Working in Taufik041/otto_test", the branch `otto/4299fa2c3f` in monospace, and a
    live elapsed timer
  - body: a list of **steps**, one row each, with an icon, a short label and a result:
    - 🔍 Searched `qualifies_for_bulk`: 2 matches
    - 📄 Read `docs/PRICING.md`
    - ✏️ Edited `src/inventory/pricing.py`: +1 −1
    - ▶︎ Ran `python -m pytest -q`: **9 passed** (green) or 2 failed (red)
    - ⎇ Committed and pushed
  - behavior:
    - the current step shows a subtle in-progress state
    - finished blocks collapse to a single summary line ("12 steps · 9 passed · 1m 48s") that can
      be expanded again
    - clicking a step, or the "Open workspace" link, opens the **workspace panel** at that step
- **PR card** (in the thread, after the work block): the PR title, `#3`, the repo, the branch,
  lines changed (+2 −1), a small "10 tests passed" check, and **"View on GitHub"**. This is the
  emotional payoff; make it feel like a finished, well-made object.
- **System notices** (small, centered, muted):
  - "Sandbox woke up from otto/4299fa2c3f"
  - "Using the warm sandbox"
  - "Rate limited, switched API key"
- **Error card:** a plain-language explanation ("The model didn't respond after 6 tries.") plus a
  **Retry** button.
- **Plain chat:** Otto just answers. When a request needs code work, Otto's reply includes a gentle
  inline prompt: "Mention a repo with @ and I'll work on it."
- **Usage limit reached:** a calm card, "You've used today's limit. It resets at midnight UTC.",
  with a link to Usage.

### 4.7 Workspace panel (on demand, like Claude's artifact panel)
- Desktop: it slides in from the right and can be resized (about 45% width by default). Mobile:
  it's a **full-screen sheet** with a close button.
- **Header:** the repo, the branch, and the sandbox state ("Warm" with a green dot, or "Asleep").
- **Tabs:**
  - **Changes:** a list of touched files with +/− counts, and a **unified diff** view with red and
    green lines and line numbers.
  - **Terminal:** every command with its output in monospace, and an exit status on each.
  - **Browser:** a designed "Browser preview — coming soon" empty state.
- The panel follows the step selected in the chat.

### 4.8 Settings
A full page with a left nav on desktop; on mobile it's a stacked list that drills into each section.

- **Account:**
  - avatar, name, email
  - change password (email accounts only)
  - linked sign-in methods (GitHub, email)
  - sign out
  - danger zone: delete account
- **GitHub:**
  - the connected account (avatar and @username)
  - the list of repositories Otto can access
  - "Add or remove repositories", which opens GitHub
  - "Disconnect"
  - a not-connected state
- **Models:**
  - the default model picker
  - the list of available models, grouped by provider, with short descriptions
  - an explanation line: "Models run on Otto's keys. Your daily limit is shown under Usage."
- **Usage:**
  - **Today:** a progress bar ("12,400 of 50,000 tokens"), with a note of when it resets
  - **This month:** sessions, tokens and estimated cost
  - a simple bar chart of tokens per day for the last 14 days (one accent color)
  - a breakdown by model
  - **active sandboxes**: count and list, each with a "Stop" action
- **Appearance:** Light / Dark / System, shown as three preview tiles.

## 5. States to design (desktop and mobile)
1. Sign in (with an error state) and sign up
2. Onboarding: connect GitHub, and the connected success state
3. Empty new chat, with suggestions
4. The `@` popover open, in both connected and not-connected states
5. The model picker open, with one OpenAI model unavailable
6. Working: a work block in progress with a live step
7. Done: a collapsed work block and the PR card
8. The workspace panel open on the Changes tab (desktop) and as a sheet (mobile)
9. A follow-up that shows "Using the warm sandbox", then new steps
10. An error card with Retry, and the usage-limit card
11. Plain chat with no repo, including the "mention a repo" nudge
12. Settings: GitHub, Usage and Appearance pages

## 6. Motion
Calm, and only in response to something happening:
- New steps fade and rise slightly into view.
- The work block collapses smoothly.
- The workspace panel slides in.
- The PR card arrives with a soft emphasis.
- The loop mark's dot travels slowly while Otto works.

Nothing bounces. Respect `prefers-reduced-motion`.

## 7. Voice
Short, plain sentences. Buttons say exactly what they do ("Connect GitHub", "Start", "Stop",
"View on GitHub"). Errors say what happened and what to do next.

## 8. Sample data (use throughout)
- **User:** Taufik Khan, `@Taufik041`
- **Connected repos:**
  - `Taufik041/otto_test` (private, updated 2h ago)
  - `Taufik041/portfolio` (public, 3d ago)
  - `Taufik041/petal` (private, 1w ago)
- **Models:**
  - OpenRouter: "OpenRouter Free" (the default, "Free, good for small tasks")
  - OpenAI: one or two models ("Fast and capable"), with one shown as unavailable in state 5
- **Chat title:** "Fix failing pricing tests"
- **User message:** "@otto_test two tests are failing, find out why and fix the source, not the
  tests"
- **Work steps:**
  1. Ran `python -m pytest -q` → **2 failed, 7 passed** (red)
  2. Searched `qualifies_for_bulk` → 2 matches (`src/inventory/pricing.py:22`,
     `src/inventory/legacy_pricing.py:15`)
  3. Read `docs/PRICING.md` ("ten units or more receives a 10% discount")
  4. Edited `src/inventory/pricing.py`:
     ```diff
     -    return quantity > config.BULK_THRESHOLD
     +    return quantity >= config.BULK_THRESHOLD
     ```
  5. Ran `python -m pytest -q` → **9 passed** (green)
  6. Committed, pushed `otto/4299fa2c3f`, and opened **PR #3** "Fix bulk discount threshold"
- **Otto's reply:** "Found it. `qualifies_for_bulk` used `>` instead of `>=`, so exactly 10 units
  missed the bulk discount. The pricing sheet says ten or more qualify. I fixed the comparison and
  all 9 tests pass. I left `legacy_pricing.py` alone because it's frozen for historical reports."
- **Follow-up:** "also add a test for exactly 11 units" → "Using the warm sandbox" → edited
  `tests/test_pricing.py` → **10 passed** → pushed to the same PR #3
- **Other chats in the sidebar:**
  - "Add line_count() to Order" (done, PR #5)
  - "Explain the catalog module" (plain chat)
  - "Refactor shipping fees" (failed)
  - "Portfolio contact form" (working)
- **Usage:** 12,400 of 50,000 tokens today; 38 sessions this month; about $0.00 on the free
  models; 1 active sandbox

## 9. Deliverable
An interactive, polished mockup covering every state in §5, at desktop and mobile widths, in both
light and dark themes. The priorities, in order:
1. the composer (`@` and the model picker)
2. the conversation, with the work block and the PR card
3. mobile
4. the workspace panel
5. Settings and auth
