---
name: DataSentry
description: Local-first dataset diagnostics that show the evidence behind every finding.
colors:
  dark-azure: "#00638E"
  azure-deep: "#004A6B"
  azure-steel: "#8CB9CC"
  light-azure: "#BFD8E3"
  paper-white: "#FFFFFF"
  onyx: "#000000"
  onyx-secondary: "#141414"
  charcoal: "#2B2B2B"
  azure-mist: "#EEF5F8"
  azure-mist-strong: "#E2EEF3"
  lifted-onyx: "#1F1F1F"
  azure-wash: "#DCEBF2"
  night-azure-wash: "#0D2A38"
  night-azure-hover: "#0A74A3"
  hairline: "#E3E6E9"
  hairline-strong: "#C8CDD2"
  night-hairline-strong: "#3D3D3D"
  ink-secondary: "#454A50"
  ink-tertiary: "#5E646B"
  night-ink-secondary: "#C9CCD0"
  night-ink-tertiary: "#9B9FA4"
  severity-high: "#B42318"
  severity-high-wash: "#FDECEB"
  severity-medium: "#9A4A00"
  severity-medium-wash: "#FCF0E4"
  severity-low-wash: "#E3EFF5"
  severity-info-wash: "#F0F2F4"
  status-pass: "#18794E"
  status-pass-wash: "#E4F3EA"
  night-severity-high: "#FF8A80"
  night-severity-high-wash: "#2C1412"
  night-severity-medium: "#F2A65A"
  night-severity-medium-wash: "#2B1D10"
  night-severity-low-wash: "#0F2430"
  night-severity-info: "#A8ACB1"
  night-status-pass: "#5CC995"
  night-status-pass-wash: "#102A1C"
typography:
  display:
    fontFamily: "Inter Display, Inter, -apple-system, BlinkMacSystemFont, SF Pro Display, Segoe UI Variable Display, Segoe UI, system-ui, sans-serif"
    fontSize: "clamp(36px, 5vw, 60px)"
    fontWeight: 600
    lineHeight: 1.05
    letterSpacing: "-0.03em"
  headline:
    fontFamily: "Inter Display, Inter, -apple-system, BlinkMacSystemFont, SF Pro Display, Segoe UI Variable Display, Segoe UI, system-ui, sans-serif"
    fontSize: "clamp(24px, 3vw, 32px)"
    fontWeight: 650
    lineHeight: 1.15
    letterSpacing: "-0.025em"
  numeral:
    fontFamily: "Inter Display, Inter, -apple-system, BlinkMacSystemFont, SF Pro Display, Segoe UI Variable Display, Segoe UI, system-ui, sans-serif"
    fontSize: "28px"
    fontWeight: 600
    lineHeight: 1.1
    letterSpacing: "-0.02em"
    fontFeature: "tnum"
  title:
    fontFamily: "Inter, -apple-system, BlinkMacSystemFont, SF Pro Text, Segoe UI Variable Text, Segoe UI, system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 650
    lineHeight: 1.3
    letterSpacing: "-0.01em"
  lede:
    fontFamily: "Inter, -apple-system, BlinkMacSystemFont, SF Pro Text, Segoe UI Variable Text, Segoe UI, system-ui, sans-serif"
    fontSize: "18px"
    fontWeight: 400
    lineHeight: 1.5
  body:
    fontFamily: "Inter, -apple-system, BlinkMacSystemFont, SF Pro Text, Segoe UI Variable Text, Segoe UI, system-ui, sans-serif"
    fontSize: "14.5px"
    fontWeight: 400
    lineHeight: 1.55
    fontFeature: "cv11, ss01"
  label:
    fontFamily: "Inter, -apple-system, BlinkMacSystemFont, SF Pro Text, Segoe UI Variable Text, Segoe UI, system-ui, sans-serif"
    fontSize: "12.5px"
    fontWeight: 500
    lineHeight: 1.4
  mono:
    fontFamily: "ui-monospace, SF Mono, Cascadia Code, JetBrains Mono, Consolas, monospace"
    fontSize: "12.5px"
    fontWeight: 400
rounded:
  chip: "8px"
  control: "10px"
  input: "12px"
  tile: "12px"
  list: "16px"
  card: "18px"
  section: "24px"
  feature: "32px"
  pill: "999px"
spacing:
  xs: "6px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  card: "22px"
  xl: "24px"
  2xl: "32px"
  hero: "56px"
components:
  button-primary:
    backgroundColor: "{colors.dark-azure}"
    textColor: "{colors.paper-white}"
    rounded: "{rounded.control}"
    padding: "0 16px"
    height: "38px"
  button-primary-hover:
    backgroundColor: "{colors.azure-deep}"
  button-secondary:
    backgroundColor: "{colors.paper-white}"
    textColor: "{colors.onyx-secondary}"
    rounded: "{rounded.control}"
    padding: "0 16px"
    height: "38px"
  button-secondary-hover:
    backgroundColor: "{colors.azure-mist-strong}"
  button-ghost:
    textColor: "{colors.ink-secondary}"
    rounded: "{rounded.control}"
    padding: "0 16px"
    height: "38px"
  button-ghost-hover:
    backgroundColor: "{colors.azure-mist}"
    textColor: "{colors.onyx-secondary}"
  input:
    backgroundColor: "{colors.paper-white}"
    textColor: "{colors.onyx-secondary}"
    rounded: "{rounded.input}"
    padding: "0 12px"
    height: "40px"
  card:
    backgroundColor: "{colors.paper-white}"
    rounded: "{rounded.card}"
    padding: "22px"
  finding-card:
    backgroundColor: "{colors.paper-white}"
    rounded: "{rounded.list}"
    padding: "14px 18px"
  upload-card:
    backgroundColor: "{colors.paper-white}"
    textColor: "{colors.onyx-secondary}"
    rounded: "{rounded.section}"
    padding: "24px"
  hero-panel:
    textColor: "{colors.paper-white}"
    rounded: "{rounded.feature}"
    padding: "64px 56px"
  pill-severity-high:
    backgroundColor: "{colors.severity-high-wash}"
    textColor: "{colors.severity-high}"
    rounded: "{rounded.pill}"
    padding: "3px 10px"
  pill-severity-medium:
    backgroundColor: "{colors.severity-medium-wash}"
    textColor: "{colors.severity-medium}"
    rounded: "{rounded.pill}"
    padding: "3px 10px"
  pill-severity-low:
    backgroundColor: "{colors.severity-low-wash}"
    textColor: "{colors.dark-azure}"
    rounded: "{rounded.pill}"
    padding: "3px 10px"
  pill-status-pass:
    backgroundColor: "{colors.status-pass-wash}"
    textColor: "{colors.status-pass}"
    rounded: "{rounded.pill}"
    padding: "3px 10px"
  chip:
    backgroundColor: "{colors.azure-mist}"
    textColor: "{colors.onyx-secondary}"
    typography: "{typography.mono}"
    rounded: "{rounded.chip}"
    padding: "1px 8px"
  theme-switch:
    backgroundColor: "{colors.azure-mist}"
    textColor: "{colors.ink-secondary}"
    rounded: "{rounded.control}"
    padding: "3px"
---

# Design System: DataSentry

## Overview

**Creative North Star: "The Calm Instrument"**

The tool is the product page. DataSentry is a calm, high-contrast instrument where evidence reads first: Paper White or pure Onyx grounds, hairline-divided surfaces, one azure action colour, and numbers set large enough to be read at a glance. It rejects the generic developer dashboard (grey cards, scattered accents, animated backdrops) and it rejects marketing gloss inside working screens.

Exactly one surface is branded: the landing hero panel, a static 32px-radius gradient field from Onyx through deep and Dark Azure to Azure Steel, holding the pitch and the upload card. Everything past the upload is the working instrument, flat and hairline-ruled, recoloured in place between a light and a dark theme. The background never moves; motion exists only to explain a change (a panel arriving, a detail opening, a toast confirming), uses opacity and a few pixels of translate, and disappears entirely under reduced motion.

Density is moderate and reading-led: 14.5px body, a page up to 1680px wide, cards that breathe at 22px, and tabular numerals wherever values are compared. Dataset strings (column names, values, finding codes) are the only monospace text, so the user's data is always visually distinct from the interface's voice.

**Key Characteristics:**
- One branded surface (landing hero panel and brand mark); every working screen is flat and ruled.
- Dark Azure is the single action fill; its readable text form flips to Azure Steel on dark grounds.
- Hairline borders and tonal steps carry structure; shadows are reserved for two floating objects.
- Severity and status colour is semantic, always paired with its word, and the only use of the pill shape.
- Light and dark themes are equals, chosen by a System/Light/Dark segmented control.
- Static background; short exponential ease-out reveals; nothing continuous except progress.

## Colors

A near-monochrome Onyx and Paper White system with a single azure family; warm and green hues appear only as severity and status markers.

### Primary
- **Dark Azure** (#00638E): the one action colour. Fills primary buttons, the dropzone tile, progress and busy bars in both themes. In light theme it is also the text form of the accent (links, selected tab underline, focus ring, data bars, low-severity marker).
- **Azure Deep** (#004A6B): primary-button hover in light theme and the second gradient stop.
- **Azure Steel** (#8CB9CC): the accent's readable text form on dark grounds (links, selected tab underline, focus ring, data bars, low severity) and the gradient's light end.
- **Light Azure** (#BFD8E3): the hero capability-list bullets, and the source hue for the light theme's nested tints.
- **Night Azure Hover** (#0A74A3): primary-button hover in dark theme, lifted rather than deepened so it stays visible on Onyx.
- **Azure Wash** (#DCEBF2) / **Night Azure Wash** (#0D2A38): selected and hovered table rows, dropzone hover, range-plot box fill.

### Neutral
- **Paper White** (#FFFFFF): light ground and light surface; the hero's text colour in both themes.
- **Onyx** (#000000): dark ground. The page is pure black in dark theme.
- **Onyx Secondary** (#141414): dark surface (cards, upload card) and the light theme's primary text.
- **Lifted Onyx** (#1F1F1F): dark nested tiles (dropzone, chips, table header, theme track).
- **Charcoal** (#2B2B2B): dark hover/pressed fill, dark hairline, theme thumb in dark, and the hairline edge that keeps the hero panel's shape on Onyx.
- **Azure Mist** (#EEF5F8) / **Azure Mist Strong** (#E2EEF3): light nested tiles and light hover/pressed fills; Light Azure at low strength rather than grey.
- **Hairline** (#E3E6E9) / **Hairline Strong** (#C8CDD2): light dividers and control borders. **Night Hairline Strong** (#3D3D3D) is the dark control border.
- **Ink Secondary** (#454A50) / **Ink Tertiary** (#5E646B): light supporting text and meta/labels. Dark counterparts **Night Ink Secondary** (#C9CCD0) and **Night Ink Tertiary** (#9B9FA4).

### Semantic (severity and status)
- **Severity High** (#B42318 light, #FF8A80 dark) on its wash; also the server-down dot and error alerts.
- **Severity Medium** (#9A4A00 light, #F2A65A dark) on its wash; also warning alerts and warn bars.
- **Severity Low** uses the accent text form (Dark Azure / Azure Steel) on a low wash.
- **Severity Info / Not evaluated** uses Ink Tertiary (light) or #A8ACB1 (dark) on a neutral wash.
- **Status Pass** (#18794E light, #5CC995 dark) on its wash; also the server-ok dot.

### Named Rules
**The Single Action Rule.** Dark Azure is the only fill that means "act". Never introduce a second accent hue; severity colours are markers, not actions.

**The One Branded Surface Rule.** The branding gradient (Onyx → Azure Deep → Dark Azure → Azure Steel) appears only on the landing hero panel and the brand mark. Working screens never carry it.

**The Readable Accent Rule.** Accent text, rules and data marks use Dark Azure on light grounds and Azure Steel on dark grounds. Dark Azure text on Onyx is never acceptable.

**The Word-Beside-Colour Rule.** Every severity or status colour appears next to its word ("high", "Issues detected"). Colour alone never carries meaning.

## Typography

**Display Font:** Inter Display, falling back to Inter, then SF Pro Display / Segoe UI Variable Display / Segoe UI / system-ui
**Body Font:** Inter, falling back to SF Pro Text / Segoe UI Variable Text / Segoe UI / system-ui
**Label/Mono Font:** ui-monospace (SF Mono, Cascadia Code, Consolas), for dataset strings only

**Character:** One neo-grotesque family in two optical roles: tight, heavy display for headlines and numerals, open text cut for reading. Inter is named first but never loaded (offline, strict CSP, no web fonts); on most machines the interface renders in SF Pro or Segoe UI, and the system must read correctly in either.

### Hierarchy
- **Display** (600, clamp(36px, 5vw, 60px), 1.05, -0.03em): the landing headline only, white on the gradient, max 14ch. 34px on phones.
- **Headline** (650, clamp(24px, 3vw, 32px), 1.15, -0.025em): the dashboard file name. The summary verdict is a sibling step (600, clamp(22px, 2.4vw, 30px), 1.2).
- **Numeral** (600-650, 26-40px, tabular): severity breakdown counts (28px), overview stat values (26px), single-figure results (40px). Always tabular-nums, display cut.
- **Title** (600-650, 15px, -0.01em): card titles, finding titles, brand name.
- **Lede** (400, 18px, 1.5): the landing explainer, max 46ch, white at 82% on the gradient.
- **Body** (400, 14.5px, 1.55): all running text; long explanations capped near 70ch.
- **Label** (500, 12.5px, sentence case): stat labels, meta text, kind/category/flags, detail-list terms, hints. Ink Tertiary. Never uppercase, never tracked out.
- **Mono** (400, 12-12.5px / 0.9em): column names, values, evidence keys, finding codes.

### Named Rules
**The Data Is Mono Rule.** Monospace is reserved for strings that come from the dataset or are machine identifiers. Interface copy is never monospace.

**The Tabular Numbers Rule.** Every number that sits next to another number (stats, counts, table cells, bars, file meta) uses tabular figures.

**The Sentence-Case Label Rule.** Labels are small, sentence-case and tertiary-coloured. No uppercase tracked labels anywhere.

## Layout

A centred page that uses wide screens: up to `--page-max` (1680px) wide with a viewport-scaled `--gutter` (clamp(20px, 3.5vw, 56px); 16px on phones), 32px top and 88px bottom padding. The sticky top bar aligns its content to the same edges. The landing is one full-width hero panel split into a flexible pitch column and an upload card capped at 580px (minimum 360px), with a clamp(40px, 6vw, 120px) gap and clamp(48px, 5vw, 96px) by clamp(36px, 5vw, 96px) padding; the headline scales up to 76px, collapsing to one column at 900px; on phones the headline and lede lead, the upload card follows immediately, and the capability list moves below it.

The dashboard reads top-down: file bar (name, meta, export actions), a summary row split 1.2fr / 1fr (verdict card, category card), an overview stat strip of six cells (three at 900px, two at 560px), then underline tabs over the active panel. The columns view pairs a table with a sticky detail panel (1.25fr / 1fr), stacking at 900px.

Spacing rhythm steps 6, 8, 12, 16, 24, 32px, with 22px card padding and 16px gaps between cards in a grid. Breakpoints: 1024px (hero padding eases), 900px (single column), 560px (phone), 480px (form grids to one column). Coarse pointers raise buttons and inputs to 44px.

## Elevation & Depth

The system is flat. Structure comes from hairline borders (1px), tonal steps (ground → surface → nested tile → hover fill) and, in dark theme, from Onyx Secondary and Charcoal surfaces lifting off a pure black ground. Only two objects float and only they cast shadows. The top bar is translucent (82% ground with a 20px saturating blur) rather than shadowed.

### Shadow Vocabulary
- **Thumb lift** (`box-shadow: 0 1px 2px` at 12% Onyx Secondary light, 50% black dark): the theme switch's sliding thumb only.
- **Float** (`box-shadow: 0 12px 32px` at 14% Onyx Secondary light, 60% black dark): the toast only.

### Named Rules
**The No Decorative Shadow Rule.** Cards, panels, buttons, the hero and the upload card are shadowless. A new shadow needs a new floating object to justify it.

**The Static Ground Rule.** The background is a flat colour (or the static hero gradient). No canvas, particles, grids or animated backdrops.

## Shapes

Softly rounded, nested by size: the larger the container, the larger the radius. The ladder is 8px (mono chips), 10px (buttons, segmented control, dropzone key), 12px (inputs, alerts, toast, dropzone tile), 16px (finding cards, tables, correction items), 18px (cards, stat strip, empty state), 24px (upload card; hero on phones), 32px (landing hero panel). Fully round (999px) is reserved for severity/status pills, progress and data bars, and 6-7px dots.

Borders are 1px hairlines everywhere; the dropzone and empty state use a 1.5px / 1px dashed border to signal "place something here". Grouped readouts (overview stats, severity breakdown, category list) are divided by internal hairlines rather than separated into boxes.

## Components

### Buttons
Quiet and solid: one filled action per view, everything else outlined or ghost.
- **Shape:** gently rounded (10px), 38px tall, 16px horizontal padding, 550 weight, 14px.
- **Primary:** Dark Azure fill, white text. Hover deepens to Azure Deep (light) or lifts to Night Azure Hover (dark).
- **Secondary (default):** surface fill with Hairline Strong border; hover fills Azure Mist Strong / Charcoal.
- **Ghost:** transparent, Ink Secondary text; hover fills the nested tint and darkens the text. Used in the top bar ("New analysis").
- **Small:** 32px tall, 12px padding, 13px. Sample-data buttons.
- **States:** press scales to 0.98 over 160ms; disabled is 50% opacity; focus is a 2px accent-ink outline offset 2px.

### Pills (severity and status only)
- **Style:** fully round, 12px/600, 3px 10px, the semantic colour as text on its wash, with a 6px dot of the same colour before the word.
- **Use:** finding severity, summary status, per-category status, failed contract checks. A zero-count pill drops its wash for a hairline outline.

### Meta text (kind, category, flags)
Not pills. 12.5px/500 Ink Tertiary text, consecutive items joined by a middle dot. Inside a split verdict the recommended strategy takes the accent text colour at 650.

### Chips
- **Style:** 8px radius, 1px hairline, nested-tint fill, 12px monospace, single-line with ellipsis. They hold dataset strings (affected columns, values).
- **State:** clickable chips take the accent-ink border and text on hover.

### Cards / Containers
- **Corner Style:** 18px (cards), 16px (finding cards, tables, corrections).
- **Background:** surface (Paper White / Onyx Secondary).
- **Shadow Strategy:** none (see Elevation & Depth).
- **Border:** 1px hairline. Finding cards tint their border with 24% of the severity colour (40% on hover); info findings stay neutral.
- **Internal Padding:** 22px (18px on phones); finding heads 14px 18px.

### Inputs / Fields
- **Style:** 40px tall, 12px radius, Hairline Strong border, surface fill, 14px text; labels 13px/600 above.
- **Hover:** border mixes 40% accent-ink.
- **Focus:** accent-ink border plus a 3px accent ring at 22%.
- **Disclosures** (parsing options, score policy, split limits) share one drawn chevron that rotates from right to down over 240ms.

### Navigation
- **Top bar:** sticky, 56px, translucent blurred ground with a hairline bottom. Brand mark (gradient tile, white lens glyph that shifts 2px on hover) and two-line lockup; a server-status line with a neutral/ok/down dot; the theme switch at the right.
- **Tabs:** text tabs (14px/500, Ink Secondary) over a hairline; the selected tab goes to primary text at 600 and grows a 2px accent-ink underline from the centre (scaleX, 240ms). Counts follow in 12px tertiary tabular figures. Horizontal scroll on narrow screens, scrollbar hidden.

### Theme Switch (signature)
Three native radios as a segmented control (System / Light / Dark with 15px stroked icons) on a nested-tint track, 10px radius, 3px inset. A solid thumb (white / Charcoal, 7px radius, thumb lift shadow) slides to the checked option over 320ms ease-out while the interface cross-fades its colours over 240ms. The choice persists in localStorage under `datasentry-theme` and is applied before first paint; labels collapse to icons on phones.

### Severity Breakdown (signature)
Four readouts (high, medium, low, info) in one row divided by hairlines, top and bottom rules, no boxes. Each holds a 28px display numeral and, beneath it, the severity word preceded by a 6px dot in its colour. A zero count greys its numeral to Ink Tertiary.

### Overview Stat Strip
Six cells in one 18px-radius strip whose internal hairlines come from a 1px gap over the hairline colour. Label (12.5px tertiary), numeral (26px/650), sub-line (12px tertiary). A wide cell holds the column-type bar: a segmented 8px round bar using the azure family and neutral greys, with a dotted legend.

### Landing Hero Panel and Upload Card
The hero is the static brand-gradient panel (110deg, 165deg when stacked), 32px radius, white type, with a Charcoal hairline in dark theme. The upload card sits on it at 24px radius (surface fill), containing a dashed 18px dropzone with a 48px Dark Azure tile (upload glyph, rises 2px on hover) and a "Browse files" key, the parsing-options disclosure, sample buttons and a privacy note under a hairline.

### Motion
Exponential ease-out (`cubic-bezier(0.16, 1, 0.3, 1)`) at 160ms for state changes and 240ms for reveals. The dashboard, each tab panel and each opened finding body rise in (opacity plus 6px translate); toasts rise 8px. Progress and busy bars are the only continuous motion. `prefers-reduced-motion: reduce` disables all animations and transitions.

## Do's and Don'ts

### Do:
- **Do** use Dark Azure (#00638E) as the only action fill, and Azure Steel (#8CB9CC) for accent text and marks on dark grounds.
- **Do** pair every severity or status colour with its word, as a pill or as a dot beside the word.
- **Do** separate grouped readouts with 1px internal hairlines instead of boxing each value.
- **Do** follow the radius ladder (8 / 10 / 12 / 16 / 18 / 24 / 32px), larger containers taking larger radii.
- **Do** set dataset strings in monospace and insert them as text; set compared numbers in tabular figures.
- **Do** design every screen in both themes; dark grounds are pure Onyx with Onyx Secondary and Charcoal surfaces.
- **Do** keep motion to 160ms/240ms exponential ease-out opacity and small translate, all removed under reduced motion.

### Don't:
- **Don't** use the branding gradient anywhere but the landing hero panel and the brand mark.
- **Don't** give kind, category or column flags the pill shape; only severity and status are pills.
- **Don't** add decorative shadows; only the theme thumb and the toast float.
- **Don't** add animated or textured backgrounds (canvas grids, particles, moving gradients).
- **Don't** load web fonts or external assets; the type must hold up in SF Pro and Segoe UI.
- **Don't** set Dark Azure text on Onyx or Onyx Secondary; switch to Azure Steel.
- **Don't** use uppercase tracked labels or eyebrow lines above headings.
