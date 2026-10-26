---
name: "Remote Job Agent — Instrument Panel, Cool"
version: "3.0.0"
updated: "2026-10-26"
source: "frontend/css/variables.css (the single source of truth; this file documents it)"
type:
  sans: "Instrument Sans 400/500/600/700"
  mono: "JetBrains Mono 400/500/600 (logs, ids, code only)"
dark:
  canvas: "#0f1320"
  sidebar: "#0a0e18"
  surface: "#161b2b"
  elevated: "#1d2335"
  hover: "#232a3e"
  inset: "#0c1120"
  rule: "#212840"
  border_subtle: "#252c44"
  border_strong: "#39415e"
  text_primary: "#e9ebf5"
  text_secondary: "#b6bdd0"
  text_muted: "#8b95ad"
  accent: "#6f5df2"
  accent_text: "#a396fa"
  cta: "#5d4ae6"
light:
  canvas: "#e4e6f2"
  sidebar: "#d8dcec"
  surface: "#eff1fa"
  elevated: "#f8f9fd"
  hover: "#e6e8f4"
  inset: "#dde0ee"
  rule: "#d5d9e9"
  border_subtle: "#cbd0e3"
  border_strong: "#b0b7d2"
  text_primary: "#14192b"
  text_secondary: "#3a4157"
  text_muted: "#596079"
  accent: "#4c37d9"
  accent_text: "#3f2ec4"
  cta: "#4c37d9"
---

# DESIGN.md — Instrument Panel, Cool (v3.0)

The product is a working instrument: a cool, tinted desk with raised panels on
it, one charged accent, and figures that line up. It is not a white SaaS
dashboard with cards floating on it, and it is not a dark "terminal" skin with
neon.

## 1. Principles

1. **A ladder, not a flat fill.** Every surface has a job. In light the page is
   lavender-grey paper, cards are a step *lighter*, the sidebar a step
   *deeper*. In dark the same order holds in its own key: page < card < raised,
   with a deeper sidebar. Nothing defaults to pure white; the only near-white
   surface is the resume preview, which is a sheet of paper.
2. **One charged accent.** Indigo is the only saturated family in the chrome:
   active navigation, the primary action, focus, links, selection, the live
   progress line. Status colours (emerald/amber/rose/cyan) are semantic and
   never decorative.
3. **A fill is not an ink.** `--primary` paints surfaces and lines;
   `--primary-text` is the same hue tuned for text on this theme's cards;
   `--control-primary-bg` + `--control-primary-ink` are the solid CTA pair.
4. **Structure by rule.** Dividers organise content, not boxes inside boxes.
   The KPI figures share one divided strip; the tracker is one board; panel
   headers are ruled. The job list is a stack of single-surface cards, each
   with one job's score, copy and actions — never a grid of bordered cells.
   Elevation is reserved for what truly floats (a hovered job card, the drawer,
   the modal, the toast).
5. **Quiet density.** 13px body, 11.5–12px metadata, 24px page title, 28px KPI
   figures, tabular numbers everywhere. No all-caps labels, no letter-spaced
   micro-type, no oversized decorative headings.

## 2. Surface ladder

| Role | Dark | Light |
|---|---|---|
| `--bg-sidebar` | `#0a0e18` | `#d8dcec` |
| `--bg-inset` (wells, inputs, table heads) | `#0c1120` | `#dde0ee` |
| `--bg-canvas` (page, header) | `#0f1320` | `#e4e6f2` |
| `--bg-surface` / `--bg-card` | `#161b2b` | `#eff1fa` |
| `--bg-surface-elevated` | `#1d2335` | `#f8f9fd` |
| `--bg-surface-hover` | `#232a3e` | `#e6e8f4` |

Rules: `--rule` divides rows inside a panel; `--border-subtle` outlines panels;
`--border-strong` / `--control-border` edge controls that must be seen;
`--overlay` / `--scrim` are the only translucent layers.

## 3. Colour

- **Accent (indigo/violet).** Dark: `--primary #6f5df2`, text `#a396fa`,
  CTA `#5d4ae6` (white ink 5.9:1), hover `#6a58f0`. Light: `--primary #4c37d9`,
  text `#3f2ec4`, CTA `#4c37d9` (white ink 7.3:1), hover `#3f2ec4`.
  `--primary-soft` is the 10–16% tint used for active nav, selected rows and
  active segmented controls.
- **Ink tiers.** Dark: `#e9ebf5` / `#b6bdd0` / `#8b95ad`, disabled `#78829c`.
  Light: `#14192b` / `#3a4157` / `#596079`, disabled `#5a6275`. Every tier
  clears 4.5:1 on the card and on the inset well; disabled also carries a shape
  signal (strike, no shadow, `not-allowed`).
- **Signals** (`-fg` on `-bg`): emerald `#4fd1a5/#10241f` · `#0f6b52/#dcefe7`;
  amber `#e8b45c/#2a2114` · `#7d5410/#f5ecd9`; rose `#ff8095/#2c1720` ·
  `#a52a3d/#f7e3e6`; cyan `#6cc4e8/#10222e` · `#175e86/#dfeaf3`;
  violet `#a396fa/#1d1a3a` · `#4c37d9/#e6e3f9`.
- **Charts.** Series 1 is the accent; then teal, amber, rose, slate
  (`--chart-1…5`), with `--chart-grid` / `--chart-axis`.
- **Console.** `--bg-console #080c16` in dark, `#1a1f2f` in light (a lifted
  blue-graphite so it sits in the paper instead of punching through it). Its
  ink is the light-on-dark set (`--text-console*`, `--console-*`) in both
  themes; the terminal is the one surface that stays a screen.
- **Paper.** `--paper-bg #fffdf8` and its rules/inks exist only for the resume
  preview, in both themes.

## 4. Typography

| Role | Size / weight | Tracking |
|---|---|---|
| Page title (`.breadcrumb-current`) | 24px / 600 | −0.022em |
| KPI figure | 28px / 600 | −0.03em |
| Section heading (panel h3, h2) | 15px / 600 | −0.014em |
| Body, table cell, button, nav | 13px / 400–500 | −0.002em |
| KPI label, form label (strong) | 12px / 600 | 0 |
| Metadata, table header, badges, timestamps | 11.5px / 500–600 | 0 |
| Legibility floor | 11px | — |

`Instrument Sans` for everything human; `JetBrains Mono` only for literal data
(log lines, run ids, code, file paths). Numbers are tabular globally
(`font-variant-numeric: tabular-nums`, `font-feature-settings: "tnum" 1`).
Headings balance (`text-wrap: balance`), paragraphs pretty.

## 5. Space, shape, motion

- Spacing scale 4 / 8 / 12 / 16 / 24 / 32 / 48. Page padding 28px desktop,
  16px at ≤768. Panel padding 20–22px, cells 14–18px.
- Radii: `--radius-sm 4`, `--radius-md 6`, `--radius-lg 8`, pill. Panels and the
  drawer use 8; controls 6; chips 4. No 14px+ consumer-app rounding.
- Shadows: `--shadow-sm` on cards that sit on the page; `--shadow-md` for the
  drawer/toast; `--shadow-lg` for modals; `--shadow-accent` on primary hover.
  No glow, no coloured drop shadows beyond the accent hover.
- Motion: 150ms `cubic-bezier(.16,1,.3,1)` for colour/shadow, 250ms for theme
  and surface changes, 320ms `cubic-bezier(.32,.72,0,1)` for the drawer.
  Toasts enter with `@starting-style` (interruptible), never a restarting
  keyframe. `prefers-reduced-motion` removes the view fade, status pulses and
  press transforms.

## 6. Components

- **Buttons.** One `primary` per screen: solid accent, white ink, 600 weight.
  `secondary`: tinted surface + visible border. `tertiary`: quiet ink, fills on
  hover. `danger`: rose tint/ink; `success`: emerald tint/ink. Height 34px
  (small 28, large 38). Disabled: inset fill, muted ink, no shadow, no spinner.
  Loading: `.is-loading` or `aria-busy="true"` spins the button's own icon and
  uses `cursor: progress` — no layout shift.
- **Badges.** 11.5px/500, 3px 7px, tint + transparent edge, radius 4. Score
  tiers are filled tints (emerald ≥85, amber 70–84, inset below) so they scan
  as a column; the value itself stays ink.
- **Navigation.** The sidebar is a labelled 252px column by default at ≥769px
  and folds to the 56px icon rail when the panel itself is clicked — the brand
  row or any empty sidebar surface, never a separate button; clicking the rail
  opens it again. The choice is stored under `localStorage['rja-sidebar']` and
  applied as `<html data-sidebar="expanded|collapsed">` before first paint
  (js/theme.js), so a collapsed sidebar never flashes open. Below 768px it is
  the off-canvas drawer, which is always labelled and has no mode. Active =
  `--primary-soft` + 2px accent marker on the inner edge (right in the rail,
  left when labelled). Brand mark is the one solid accent in the chrome.
- **Tables and lists.** Table heads sit on `--bg-inset` at 11.5px/600 with a
  rule; rows are divided by `--rule`, hover `--bg-surface-hover`, selected
  `--primary-soft` + 2px left bar. Curated Jobs is a responsive grid of job
  cards — 1/2/3/4 columns as width allows, each a raised surface holding the
  score tile, the role, the company and date, the meta, a two-line read of the
  description, the stack and the actions. 14px gap; a card lifts 2px to
  `--bg-surface-elevated` + `--shadow-md` on hover, and selection adds a
  primary ring. `Tailor` is secondary, `Inspect` tertiary (the card opens the
  drawer). Empty, loading and error states span the grid as cards too, so the
  canvas never looks like a broken table. Entering the view deals the cards in
  with a 300ms rise-and-settle, staggered 22ms across the first twelve; it is
  the one orchestrated entrance on the screen, and a filter change re-renders
  without replaying it.
- **Panels.** KPI strip is one raised, divided face (no hover; not controls).
  Dashboard widgets, monitor panels and the tracker board share the same face
  and a ruled header, so a section starts the same way everywhere.
- **Forms.** Inputs sit on `--bg-inset` with `--control-border`, radius 6,
  focus = `--border-focus` + 3px `--ring`. Labels 12px/600 secondary.
  Range inputs are restyled (theme track, accent thumb) because native chrome
  refuses the palette.
- **Drawer / modal / toast.** Drawer is `--bg-surface` over `--scrim` (mobile:
  full screen over `--scrim`); summary cards inside are `--bg-inset` wells.
  Modal is 8px, `--border-subtle`, `--shadow-lg` over `--overlay`. Toast is an
  inverse chip in both themes with an emerald/amber icon.
- **Console.** Dark slab, 2px progress line, 62/100/flex event columns, mono
  11.5px/1.75; status chips use the tint/ink pairs above.

## 7. Accessibility

- Text contrast measured in a real browser: 0 failures at 4.5:1 in dark, light,
  and both login pages (see §8). Large text and UI edges clear 3:1.
- Focus is always visible: 2px `--border-focus`, 2px offset, plus a 3px ring on
  inputs. Nothing important is hover-only; row actions are always rendered.
- Tap targets ≥44px on phones (mobile harness reports none failing), 16px input
  font on mobile to stop iOS zoom, safe-area padding on the drawer and header.
- State is never colour alone: locked submit is struck through and disabled;
  selected rows carry a bar; disabled buttons lose their shadow.

## 8. Verification

- This pass used three throwaway browser harnesses (outside the repo): a
  screenshot/overflow/console runner (24 shots: 6 views × dark/light at 1440,
  plus 768/390 dashboard, jobs and drawer), a contrast auditor that measures
  every visible text node in both themes plus the open drawer and both login
  pages, and a phone-level checker (clipped text, tap-target heights, theme
  persistence, drawer Escape/focus return).
- Results at the end of the pass: 24 shots, 0 console errors, no horizontal
  overflow at 1440/1024/768/390/320; contrast 0 failures in dark, light,
  login-dark and login-light; phone check 0 clipped elements, 0 under-size tap
  targets, theme persisted across reload.
- The committed checks are `tests/e2e/*.test.mjs` (jsdom against a live API)
  and `tests/` (pytest). Run them after a visual change; they assert the
  header/layout contract, breakpoint ladder and the data flows, not pixel
  values.

## 9. Rules for changing the interface

1. Add colour to `frontend/css/variables.css` **in both themes**, with a name
   that says what it is for. Never hardcode a hex/rgba outside that file
   (`grep -E '#[0-9a-fA-F]{3,8}|rgba?\(' frontend/css/*.css` must only match
   `variables.css`).
2. Pick the token by role: page vs card vs well; ink tier; fill vs ink vs solid
   CTA pair; signal fg vs bg.
3. Keep the surface ladder ordered: sidebar < inset < canvas < surface <
   elevated < hover (light may swap which side "recessed" reads on, but the
   values must stay distinct).
4. Respect the type scale; do not add a new size for one label. Figures are
   tabular.
5. Bump the `?v=` cache stamp in `index.html` (and `login.html`) when tokens or
   component CSS change; both pages currently use `v=4`.
6. Re-run the browser pass (both themes, 1440/1024/768/390, console + overflow +
   contrast) and the e2e suites under `tests/e2e/` before calling a visual
   change done.
