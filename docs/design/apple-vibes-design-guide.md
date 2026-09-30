# Apple Vibes — a reusable design guide

A portable design system that captures the look and feel of Apple's own product
pages and Human Interface Guidelines. Drop this into any project (portfolio, café
site, diary app, dashboards) to start from a coherent, premium aesthetic instead
of re-deciding every time.

The whole system rests on one idea: **restraint is the style.** Apple's pages look
expensive because almost everything is quiet — huge whitespace, near-black text on
near-white, one typeface, one accent color — so the one thing that matters (a
product, a headline, an image) carries all the weight. If you remember nothing
else: *spend your boldness in exactly one place and keep everything else calm.*

---

## 1. Principles

1. **Content is the hero, chrome disappears.** No decorative borders, boxes, or
   gradients competing with the actual thing. The nav is thin and gets out of the
   way. The product shot or headline owns the screen.
2. **Whitespace is not empty — it's the design.** Apple uses far more negative
   space than feels comfortable. Generous top/bottom padding on every section,
   wide margins, air around headlines. When in doubt, add space.
3. **One accent, used rarely.** The palette is essentially white, near-black, and
   grays. A single blue (or one brand color) appears only on links and primary
   actions. Color is a signal, never decoration.
4. **Big, confident type; short, declarative copy.** Headlines are large and
   tightly tracked. Sentences are short and end with periods for rhythm.
   "So strong. So light." Say less.
5. **Sharp imagery, edge to edge.** Photography and product renders are
   high-resolution, well-lit, often full-bleed or centered on a light gray stage.
   No stock-photo clutter.
6. **Motion is invisible until it's needed.** Nothing bounces or slides for
   decoration. Subtle scroll reveals and honest interaction feedback only.
   Respect `prefers-reduced-motion`.
7. **Flat, no fake depth.** No drop shadows for decoration, no glassy bevels, no
   heavy gradients. Depth comes from spacing and hierarchy, not effects. (Soft,
   barely-there shadows are allowed only to lift a card off a gray background.)

---

## 2. Color

Apple's palette is deliberately tiny. The signature move is **near-black text on
near-white**, plus Apple's famous light gray (`#f5f5f7`) for alternating sections.

### Light mode
| Role | Hex | Notes |
|---|---|---|
| Background (primary) | `#ffffff` | Pure white base |
| Background (secondary) | `#f5f5f7` | The signature Apple light gray — alternate sections |
| Text (primary) | `#1d1d1f` | Near-black, **never pure `#000`** — softer, more premium |
| Text (secondary) | `#6e6e73` | Captions, sublines, muted labels |
| Accent / links | `#0071e3` | Apple blue — primary buttons, links |
| Accent (hover) | `#0077ed` | Slightly brighter on hover |
| Hairline / borders | `#d2d2d7` | 1px dividers, input outlines |

### Dark mode
| Role | Hex | Notes |
|---|---|---|
| Background (primary) | `#000000` | Apple goes true black in dark mode |
| Background (secondary) | `#1d1d1f` | Alternate sections / cards |
| Text (primary) | `#f5f5f7` | Off-white |
| Text (secondary) | `#86868b` | Muted |
| Accent / links | `#2997ff` | Brighter blue for dark backgrounds |
| Hairline / borders | `#424245` | Subtle dividers |

**Rules of thumb:** never pure black text, never more than one accent, keep large
areas white or gray. If you want a brand color other than blue, swap *only* the
accent row and keep everything else — that's how you make it "Apple, but yours."

---

## 3. Typography

Apple ships **SF Pro** (Display for large sizes, Text for body). SF Pro is licensed
for Apple platforms, so on the web use the system stack, which renders SF on Apple
devices and a clean fallback elsewhere. **Inter** is the closest free match if you
want consistent rendering everywhere.

```css
/* System stack — renders real SF on Apple devices */
font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text",
             "Helvetica Neue", Inter, Arial, sans-serif;
```

**One family only.** Apple does not pair a display serif with a sans — it's all SF,
differentiated by size and weight. Two weights carry the whole system: **regular
(400)** for body, **semibold (600)** for headlines. Occasionally **medium (500)**
for buttons/nav.

### Type scale
| Element | Size (desktop) | Weight | Line-height | Tracking |
|---|---|---|---|---|
| Hero headline | 48–80px | 600 | 1.05 | -0.02em (tight) |
| Section heading | 32–48px | 600 | 1.1 | -0.02em |
| Subheading | 21–28px | 500 | 1.2 | -0.01em |
| Body | 17–19px | 400 | 1.5 | normal |
| Caption / secondary | 12–14px | 400 | 1.4 | normal |

**Key tells of the Apple look:** large headlines, **semibold not bold**, and
**negative letter-spacing** on big type (this tightening is what makes it feel
Apple rather than generic). Body text sits around 17px — larger than the web
default. Keep line length under ~70 characters.

**Case:** headlines and body in **sentence case**. Product/proper names keep their
real casing. Avoid ALL-CAPS eyebrow labels — that's the generic-template tell,
and Apple doesn't do it.

---

## 4. Spacing & layout

Generosity is the whole game. Apple's sections breathe.

- **Spacing scale (8px base):** 4, 8, 12, 16, 24, 32, 48, 64, 80, 120, 160.
  Use the *large* end freely — section padding is often 80–120px top and bottom.
- **Content width:** center a max-width container. Text blocks ~680–720px;
  wider grids ~980–1200px. Apple centers most hero content.
- **Alignment:** hero and marketing sections are **center-aligned**; dense content
  (specs, docs, lists) is left-aligned. Don't center long paragraphs.
- **Rhythm:** alternate `#ffffff` and `#f5f5f7` sections down the page to create
  bands without borders.
- **Radius:** Apple uses generous corner radius. Cards ~18–20px, buttons fully
  rounded (pill) or ~12px, images ~18px. Pick one card radius and stay consistent.

---

## 5. Components

### Buttons
Apple's primary button is a **blue pill** with white text; the secondary is a
**text link with a chevron** or an outlined pill.

```css
.btn-primary {
  background: #0071e3;
  color: #fff;
  font-size: 17px;
  font-weight: 400;
  padding: 12px 22px;
  border-radius: 980px;   /* fully rounded pill */
  border: none;
}
.btn-primary:hover { background: #0077ed; }

.btn-secondary {          /* Apple's classic text link */
  color: #0071e3;
  font-size: 17px;
  background: none;
  border: none;
}
/* Apple often appends a chevron, e.g. "Learn more ›" — use sparingly */
```

### Cards
Flat, rounded, sitting on the gray section background. Minimal or no border; a
*very* soft shadow only if it needs lifting.

```css
.card {
  background: #fff;
  border-radius: 18px;
  padding: 32px;
  /* optional, barely-there lift: */
  box-shadow: 0 4px 24px rgba(0,0,0,0.04);
}
```

### Navigation
Thin, translucent, sticky. Small text, generous horizontal spacing, brand left,
links right. Apple's real nav uses a frosted `backdrop-filter: blur()` over a
semi-transparent background.

```css
.nav {
  height: 48px;
  background: rgba(255,255,255,0.8);
  backdrop-filter: saturate(180%) blur(20px);
  border-bottom: 1px solid #d2d2d7;
  font-size: 14px;
}
```

### Forms & inputs
Rounded, hairline border, generous padding, blue focus ring. Labels in plain
sentence case above the field.

```css
.input {
  border: 1px solid #d2d2d7;
  border-radius: 12px;
  padding: 12px 16px;
  font-size: 17px;
}
.input:focus { border-color: #0071e3; outline: 2px solid rgba(0,113,227,0.3); }
```

---

## 6. Motion

- **Scroll reveals:** a single, subtle fade + small rise (8–16px) as sections
  enter. Slow and soft (~0.6s ease-out). Not on every element — on section
  arrivals only.
- **Hover:** gentle. Links brighten, buttons shift shade, images scale ~1.02.
  No large transforms.
- **Interaction feedback:** motion that answers a click (a panel opening, a value
  updating) is welcome because it shows what changed.
- **Always** respect `@media (prefers-reduced-motion: reduce)` and disable
  non-essential animation.

The Apple feeling is *calm confidence* — if an animation calls attention to
itself, cut it.

---

## 7. Imagery & icons

- **Product / subject as hero:** one large, sharp, well-lit image or render,
  centered on white or `#f5f5f7`, with lots of space around it.
- **Full-bleed** for atmosphere sections; **centered on a stage** for product
  focus.
- **Icons:** thin, consistent line weight, monochrome (SF Symbols style). Don't
  mix filled and outline styles. Tabler Icons or Lucide (outline set) are good
  free stand-ins.
- No busy backgrounds, no photo collages, no drop-shadowed clip art.

---

## 8. Voice & copy

The words are part of the design. Apple's copy is short, confident, and concrete.

- Short declarative sentences. Periods for rhythm: "Fast. Fluid. Familiar."
- Say what it *is* or *does*, plainly — don't oversell with adjectives stacked on
  adjectives (ironically, do this *once* for effect, then stop).
- Sentence case. Active voice. A button says exactly what it does ("Get started",
  not "Submit"), and the same word carries through the flow.
- Empty states and errors are directions, not apologies: say what happened and
  what to do next.

---

## 9. Anti-patterns (what breaks the Apple vibe)

- Pure black (`#000`) text on white — use `#1d1d1f`.
- More than one accent color, or accent used as decoration.
- Bold (700+) headlines — Apple is semibold (600).
- Tight, cramped sections — the whole look depends on generous whitespace.
- Drop shadows, gradients, glass bevels used for decoration.
- ALL-CAPS eyebrow labels above every heading.
- Multiple typefaces, or a display serif paired with a sans.
- Center-aligned long paragraphs.
- Motion on everything — reveals and hovers everywhere read as generic/AI-made.

---

## 10. Paste-ready prompt

Copy this into Claude Design or Claude Code, then add your project's specific
sections and content underneath.

```
Design/build this with an "Apple vibes" aesthetic — the look and feel of Apple's
own product pages. Restraint is the style: huge whitespace, near-black text on
near-white, one typeface, one accent, and the single most important thing on each
screen carries all the weight.

COLOR (light mode)
- Background: #ffffff, with alternating sections in Apple gray #f5f5f7.
- Text: #1d1d1f primary (never pure black), #6e6e73 secondary.
- One accent only — Apple blue #0071e3 — used solely on primary buttons and links.
- Hairline borders/dividers: #d2d2d7. Support a dark mode: #000 bg, #f5f5f7 text,
  #2997ff accent.

TYPOGRAPHY
- One family: the system stack (-apple-system, BlinkMacSystemFont, "SF Pro
  Display", "SF Pro Text", Inter, sans-serif). No serif pairing.
- Two weights: 400 body, 600 headlines (semibold, NOT bold). 500 for buttons/nav.
- Large headlines (48–80px hero) with tight negative letter-spacing (-0.02em),
  line-height ~1.05. Body ~17px, line-height 1.5, line length under ~70 chars.
- Sentence case everywhere; proper names keep their casing. No ALL-CAPS labels.

LAYOUT & SPACING
- 8px spacing scale; use the large end — section padding 80–120px top/bottom.
- Centered max-width container: ~680–720px for text, ~1100px for grids.
- Center-align hero/marketing content; left-align dense content. Never center long
  paragraphs. Alternate white and #f5f5f7 section bands instead of borders.
- Corner radius: cards ~18px, buttons pill (fully rounded) or 12px, images ~18px.

COMPONENTS
- Primary button: blue #0071e3 pill, white text, ~12px/22px padding, no border.
- Secondary: plain blue text link. Cards: flat, rounded 18px, white on gray, at
  most a whisper-soft shadow. Nav: thin (~48px), sticky, translucent with a
  frosted blur, small text, brand left / links right.

MOTION
- Minimal and calm. One subtle fade + small rise on section scroll-in; gentle
  hover states only. Respect prefers-reduced-motion. Nothing decorative bounces.

VOICE
- Short, confident, concrete copy. Active voice. Buttons name their exact action.

AVOID (these break the vibe): pure #000 text, more than one accent, bold headlines,
cramped spacing, decorative shadows/gradients, ALL-CAPS eyebrows, multiple
typefaces, motion on every element.
```

---

*Reuse this across projects by keeping sections 2–4 (color, type, spacing) fixed
and only swapping the accent color to rebrand. That single change turns "Apple" into
"your Apple."*
