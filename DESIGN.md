---
name: DataSentry
description: Local-first dataset diagnostics that show the evidence behind every finding.
colors:
  ledger-blue: "#2f5bd3"
  ledger-blue-deep: "#2549b0"
  ledger-blue-wash: "#e8eefc"
  ledger-blue-dark: "#7a9cf5"
  ledger-blue-deep-dark: "#9bb4f8"
  ledger-blue-wash-dark: "#1d2843"
  paper: "#f6f7f9"
  sheet: "#ffffff"
  sheet-tint: "#f1f3f6"
  rule-line: "#dfe3ea"
  rule-line-strong: "#c9cfd9"
  ink: "#182031"
  ink-soft: "#4a5468"
  ink-faint: "#5f687a"
  night-paper: "#0f131a"
  night-sheet: "#161b24"
  night-sheet-tint: "#1c2330"
  night-rule-line: "#2a3242"
  night-rule-line-strong: "#3a4458"
  night-ink: "#e6e9ef"
  night-ink-soft: "#b5bdcc"
  night-ink-faint: "#8b94a7"
  severity-high: "#b42318"
  severity-high-wash: "#fdecea"
  severity-medium: "#a64b00"
  severity-medium-wash: "#fdf0e3"
  severity-low: "#1d5bbf"
  severity-low-wash: "#e7effb"
  severity-info: "#556074"
  severity-info-wash: "#eef0f4"
  status-pass: "#18794e"
  status-pass-wash: "#e4f4ec"
  severity-high-dark: "#f97066"
  severity-medium-dark: "#f5a35c"
  severity-low-dark: "#84adf5"
  severity-info-dark: "#a3acbd"
  status-pass-dark: "#4fc58c"
  bar-track: "#e6e9ef"
typography:
  display:
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif"
    fontSize: "clamp(28px, 4vw, 40px)"
    fontWeight: 700
    lineHeight: 1.15
    letterSpacing: "-0.02em"
  headline:
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif"
    fontSize: "22px"
    fontWeight: 650
    lineHeight: 1.3
    letterSpacing: "-0.01em"
  title:
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif"
    fontSize: "17px"
    fontWeight: 600
    lineHeight: 1.4
  body:
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.55
  label:
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif"
    fontSize: "12px"
    fontWeight: 650
    lineHeight: 1.4
    letterSpacing: "0.04em"
  data:
    fontFamily: "ui-monospace, Cascadia Code, SF Mono, Consolas, monospace"
    fontSize: "12.5px"
    fontWeight: 400
    lineHeight: 1.5
rounded:
  sm: "6px"
  md: "10px"
  lg: "14px"
  pill: "999px"
spacing:
  xs: "6px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
components:
  button:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "0 14px"
    height: "36px"
  button-hover:
    backgroundColor: "{colors.sheet-tint}"
  button-primary:
    backgroundColor: "{colors.ledger-blue}"
    textColor: "{colors.sheet}"
    rounded: "{rounded.sm}"
    padding: "0 14px"
    height: "36px"
  button-primary-hover:
    backgroundColor: "{colors.ledger-blue-deep}"
  button-small:
    rounded: "{rounded.sm}"
    padding: "0 10px"
    height: "30px"
  input:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "0 10px"
    height: "36px"
  card:
    backgroundColor: "{colors.sheet}"
    rounded: "{rounded.md}"
    padding: "18px"
  pill-severity-high:
    backgroundColor: "{colors.severity-high-wash}"
    textColor: "{colors.severity-high}"
    rounded: "{rounded.pill}"
    padding: "2px 10px"
  chip-data:
    backgroundColor: "{colors.sheet-tint}"
    textColor: "{colors.ink}"
    typography: "{typography.data}"
    rounded: "{rounded.sm}"
    padding: "1px 8px"
  tab-active:
    textColor: "{colors.ledger-blue}"
    padding: "10px 14px"
---

# Design System: DataSentry

## Overview

**Creative North Star: "The Lab Notebook"**

DataSentry looks like a careful researcher's notebook: neutral, ruled pages where every entry
records what was measured, what it might mean and how sure we are. The interface is a working
tool for a technical user who wants to know quickly what could hurt their model. The design
therefore spends its energy on legibility, ordering and evidence, not on atmosphere. Brand lives
in precise details: tabular numerals, monospace for anything that came from the dataset, hairline
rules, and a single disciplined accent.

Density is comfortable-compact. Cards and tables sit close together on a pale paper ground, with
generous internal padding and tight gutters, so a full summary, overview and findings list fit in
one or two screens. Severity color appears as small markers (a pill, a dot, a tinted hairline), never as
large fills, so the page stays calm even when it reports a serious problem. Light and dark themes
are equal citizens: by default the page follows the operating system, and a three-way switch in
the top bar (System / Light / Dark) lets the user override it.

The system rejects two directions explicitly: **alarmist red dashboards** (walls of red, warning
iconography, panic color for ordinary observations) and **marketing gloss** (gradients, glows,
hero illustrations, neon).

**Key Characteristics:**
- Paper-and-ink neutrals with one accent, Ledger Blue.
- Flat surfaces separated by 1px rules and tonal steps; at most a whisper of shadow in light mode.
- System sans for interface text; monospace for column names, values and other dataset strings.
- Severity is coded by color *and* text label, always as a small marker.
- Tabular numerals wherever numbers are compared.

## Colors

A cool paper-and-ink palette with one blue accent and a muted five-step status scale.

### Primary
- **Ledger Blue** (light `ledger-blue`, dark `ledger-blue-dark`): primary buttons, the selected
  tab, links, focus rings, data bars, the dropzone icon and selected table rows (via
  `ledger-blue-wash`). `ledger-blue-deep` is its hover state. In dark mode the accent lightens, and
  primary buttons switch to dark text on the light blue.

### Neutral
- **Paper** (`paper` / `night-paper`): the page ground behind all cards.
- **Sheet** (`sheet` / `night-sheet`): cards, tables, inputs, the top bar.
- **Sheet Tint** (`sheet-tint` / `night-sheet-tint`): nested fills such as key-value tiles,
  category cells, table headers, the dropzone and data chips.
- **Rule Line / Strong Rule** (`rule-line`, `rule-line-strong` and night variants): card borders
  and dividers; strong rules for input and button outlines.
- **Ink, Soft Ink, Faint Ink** (`ink`, `ink-soft`, `ink-faint` and night variants): primary text,
  secondary text, and metadata or labels respectively.

### Status (semantic, not decorative)
- **Severity High / Medium / Low / Info** (`severity-*`, each with a `-wash` background and a
  `-dark` text variant): finding severity, as a pill and a faint tint in the finding card's 1px border.
- **Status Pass** (`status-pass`): the "Pass" category status only.

### Named Rules
**The One Voice Rule.** Ledger Blue is the only accent. It marks what the user can act on or has
selected; it is never used as decoration.

**The Marker, Not Fill Rule.** Status colors appear as small markers (pills, dots, a tinted hairline,
bar fills). They never flood a card, a header or the page.

**The Word Beside the Color Rule.** Every status color is paired with its word ("high", "Issue",
"Pass"). Color alone never carries meaning.

## Typography

**Display Font:** system UI sans (`system-ui`, -apple-system, Segoe UI, Roboto, …)
**Body Font:** the same system UI sans
**Label/Mono Font:** system monospace (`ui-monospace`, Cascadia Code, SF Mono, Consolas)

**Character:** a single native sans that feels at home in the user's OS, paired with monospace
for everything that came from the dataset. No web fonts are loaded; the app must work offline.

### Hierarchy
- **Display** (700, clamp(28px, 4vw, 40px), 1.15): the landing headline only.
- **Headline** (650, 22px): the dataset filename and stat values.
- **Title** (600, 17px): the summary headline. Card titles use 650 at 14px; finding titles 600 at
  14.5px.
- **Body** (400, 14px, 1.55): all running text. Lede copy is 16px with a 54ch measure.
- **Label** (650, 12px, 0.04em, uppercase): section labels inside panels. Ordinary metadata uses
  12–12.5px in Faint Ink without uppercase.
- **Data** (monospace, 12.5px): column names, category values, codes and chips.

### Named Rules
**The Dataset-in-Mono Rule.** Any string that originated in the user's file (column name, value,
label) is set in monospace, so it is instantly distinguishable from interface copy.

**The Tabular Figures Rule.** Numbers that are compared (stats, counts, table columns) use
`font-variant-numeric: tabular-nums` and right alignment in tables.

## Layout

A centered column with a 1200px maximum width and a 16px side gutter, under a sticky top bar.
The landing view is two columns (headline and capability list beside the upload card) that stack
below 900px. The dashboard stacks a file bar, a two-column summary (quality summary beside checks
by category), a row of auto-fit stat cards (minimum 150px each), a horizontally scrollable tab
strip and the active tab panel. The columns tab is a table beside a sticky detail panel, which
also stacks below 900px.

Spacing follows an 8px base with frequent 12px and 16px steps; 24px separates major dashboard
bands. Below 560px, detail lists collapse to one column, bar rows wrap their bar underneath, and
the file actions fill the width.

### Kinetic grid background
A full-viewport canvas behind all content (`frontend/kinetic-grid.js`), added at the user's request.
A 55px grid of Ink hairlines (13% opacity) with faint nodes over a 28px dot texture, painted on the
Paper color. Within 260px of the pointer the grid bends away by up to 24px and lines, nodes and a
soft node glow shift to Ledger Blue; a press sends out a fading Ledger Blue ripple. Colors are read
from the theme tokens and update with the theme switch. Cards, tables and the top bar stay opaque,
so the grid shows only in the gaps. It draws a still grid under `prefers-reduced-motion`, sleeps
when the pointer settles, and pauses in hidden tabs.

## Elevation & Depth

Flat with hairlines. Depth comes from tonal layering (Paper, then Sheet, then Sheet Tint) and 1px
rules. Light mode adds one near-invisible ambient shadow to cards so they separate from the
paper; dark mode removes it entirely and relies on tone. The only floating element is the toast.

### Shadow Vocabulary
- **Sheet whisper** (`box-shadow: 0 1px 2px rgba(16, 24, 40, 0.06), 0 1px 3px rgba(16, 24, 40, 0.06)`):
  cards, finding cards and the upload card in light mode. Never in dark mode.
- **Toast float** (`box-shadow: 0 6px 20px rgba(0, 0, 0, 0.2)`): the transient toast only.

### Named Rules
**The Flat-By-Default Rule.** Surfaces never lift on hover. State is shown by tone, border color or
the accent, not by shadow.

## Shapes

Gently rounded rectangles. Controls, tiles, chips and alerts use a 6px radius; cards and tables
10px; the landing upload card 14px. Pills and bar tracks are fully rounded. Borders are always
1px, except the 2px underline on the selected tab and the 1.5px dashed outline of the
dropzone.

## Components

### Buttons
Quiet and exact.
- **Shape:** gently rounded (6px), 36px tall, 0 14px padding, weight 550.
- **Default:** Sheet background, Strong Rule border, Ink text; hover tints to Sheet Tint.
- **Primary:** Ledger Blue fill and border with white text (dark text in dark mode); hover deepens
  to Ledger Blue Deep. One primary button per region.
- **Small:** 30px tall, 0 10px, 13px text, for secondary actions such as sample datasets.
- **Ghost:** no border or fill; used for "New analysis" in the top bar.
- **Disabled:** 55% opacity with a not-allowed cursor.
- **Focus:** a 2px Ledger Blue outline offset by 2px (global `:focus-visible`).

### Pills and Chips
- **Severity / status pill:** fully rounded, 12px semibold, a 7px dot in the current color, the
  status word, and its wash background. Zero counts drop to an outlined, faint pill.
- **Outline pill:** Strong Rule border and Soft Ink text, for kinds, categories and column flags.
- **Data chip:** monospace on Sheet Tint with a 6px radius. When it is a button (a column link),
  hover turns the border and text Ledger Blue.

### Cards / Containers
- **Corner Style:** 10px.
- **Background:** Sheet, with Sheet Tint for nested tiles.
- **Shadow Strategy:** sheet whisper in light mode only (see Elevation & Depth).
- **Border:** 1px Rule Line.
- **Internal Padding:** 18px (stat cards 14px 16px).

### Inputs / Fields
- **Style:** 36px tall, Sheet background, 1px Strong Rule border, 6px radius, 0 10px padding.
  Search inputs grow to fill the toolbar.
- **Focus:** the global 2px Ledger Blue outline.

### Navigation
- **Top bar:** sticky Sheet bar with a bottom rule: the brand lockup, the server-status pill, a
  ghost "New analysis" action and the theme switch. Below 560px the status pill and tagline are
  removed and the switch shows icons only.
- **Brand lockup:** a 34px Ledger Blue tile (8px radius) holding faint data rows and an
  on-accent lens, beside an uppercase wordmark (13.5px, 750, 0.09em tracking) over a monospace
  "dataset diagnostics" tagline in Faint Ink. Its one authored motion: on hover or keyboard focus the
  lens shifts up-left and a scan line sweeps the rows once (520ms / 900ms, exponential ease-out).
  The favicon uses the same mark.
- **Server-status pill:** fully rounded, Sheet Tint with a 1px rule, Soft Ink text and a 7px dot
  that reports the real health check: Faint Ink while connecting, Status Pass when reachable,
  Severity High when unreachable.
- **Theme switch:** three native radios (System / Light / Dark) in a fully rounded Sheet Tint track
  with a 1px rule. A tinted-glass thumb (Ledger Blue at 22% over translucent Sheet, a 45% accent
  edge and a faint top highlight) slides to the checked option in 480ms with exponential ease-out.
  The checked label is Ink for AA contrast on the tint, and its icon is Ledger Blue and answers with
  its own motion: the monitor lifts, the sun turns 90°, the moon tilts. Native arrow keys move and
  select. The choice persists in local storage and is applied before first paint; "System" clears it.
- **Tabs:** text tabs with a 2px underline. Selected is Ledger Blue; others are Soft Ink and turn
  Ink on hover. Counts sit beside labels in Faint Ink. Arrow keys move between tabs.

### Dropzone (instrument slot)
The upload target on the landing view. A Sheet Tint panel with a 1.5px dashed Strong Rule border
and 10px corners, laid out as a slot: a 50px icon tile (Ledger Blue Wash, 6px radius, accent
upload arrow), the title and limits hint beside it, and a "Browse files" key on the right (Sheet
fill, Strong Rule border with a 2px bottom edge). On hover or drag-over the border turns Ledger
Blue, the panel tints to Ledger Blue Wash, the tile rises 2px and the key turns accent. Below
560px the key drops to a full-width row while the tile stays beside the text. The whole panel is
the single keyboard-focusable control; the key is decorative.

### Finding Card (signature)
The core unit of the notebook. A Sheet card whose 1px border takes a faint (22%) tint of the
severity color on every side, with a row of pills (severity, kind, category), a 14.5px title and a one-line explanation. It expands with an
accessible disclosure to a two-column definition list: what was found, affected columns as data
chips, why it matters, the next step, limitations, an evidence table in monospace and the
finding code.

### Data Readouts
- **Stat card:** a faint label, a 22px tabular value, and an optional faint sub-line.
- **Key-value tile:** Sheet Tint, 6px radius, an 11.5px faint label over a semibold tabular value.
- **Bar row:** a monospace label, a 10px fully rounded bar in Ledger Blue on Bar Track
  (Severity Medium when flagged), and a right-aligned value.
- **Range plot:** a min–max track with a Ledger Blue IQR box and median tick, labelled at the ends,
  with an equivalent `aria-label`.

## Do's and Don'ts

### Do:
- **Do** keep Ledger Blue as the only accent, reserved for actions, selection, focus and data bars.
- **Do** set every dataset-originated string in monospace and insert it as text.
- **Do** pair every severity or status color with its word.
- **Do** use tabular numerals and right alignment for compared numbers.
- **Do** separate surfaces with 1px rules and tonal steps; keep dark mode shadow-free.
- **Do** keep both themes at WCAG 2.2 AA contrast and respect `prefers-reduced-motion`.
- **Do** define each color once with `light-dark()` so the OS preference and the theme switch
  share a single source of truth.

### Don't:
- **Don't** build alarmist red dashboards: no red-filled cards or headers, no warning-icon walls,
  no panic color for observations such as imbalance or outliers.
- **Don't** add marketing gloss: no gradients, glows, neon, hero illustrations or decorative
  animation. The one sanctioned exception is the kinetic grid background (see Layout), added at
  the user's explicit request.
- **Don't** introduce a second accent hue or load web fonts.
- **Don't** lift elements with shadow on hover.
