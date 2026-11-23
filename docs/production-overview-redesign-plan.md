# Production overview redesign: five directions

Status: **options only.** Nothing in `app/` changes. The mockups live in
`docs/design-options/production-overview/` (open `index.html`) and use a snapshot of the
`ui_shots.py seed stock production lineage` data, so all five show the same seven batches.

The founder asked for a full overhaul of the page's look and feel, five different options,
ignoring the current colours and house style. That overrides the page-design skill's
"three styles in the house style" rule for this round. When a direction is chosen it gets
built into `app/core/frontend/core/core2.html` in a follow-up MR, and only the winning
direction's tokens move into the design system.

## What the page must answer

In one sentence: **what is being made right now, what needs me, and what do I do next.**
The page currently answers it with five equally weighted boxes: health, six "at a glance"
figures, the batch list, actions and links. Observed in `00-before` (1440 wide):

- The batch list, the thing people come for, starts 670 px down. The six figure cards
  above it are 170 px tall each to hold one number.
- Health ("Action required") and the figures sit side by side with equal weight, so
  nothing leads.
- Seven identical "Record next step" buttons, all in the same outline style, make the
  list read as a column of buttons.
- Stock movements in 24 h shows 0 at the same size as the number of active batches.
- One accent (teal) is used for nav, tabs, primary button, progress bars and links, so it
  stops meaning "act here".

## What other products do

| Pattern | Where from | What it changes here |
|---|---|---|
| Separate top-level menus by job; Reporting promoted to the main nav | Xero's 2025 navigation (Sales, Purchases, Tax, Reporting menus) | Option 3 keeps a short top text nav (Home, Production, Sales, Compliance) instead of a sidebar |
| Left sidebar for many sections, pinned shortcuts | Stripe Dashboard (May 2024 update, shortcuts); Shopify admin nav on the left, dropdown from the title bar on mobile | Option 1 keeps a full sidebar with Production's sub-pages nested under it |
| Dim the sidebar once you have arrived; softer borders | Linear UI refresh, March 2026 ("navigation sidebar … dimmed") | Option 1's sidebar is low-contrast; the content has the only strong surfaces |
| Horizontal tabs → resizable sidebar on desktop, floating bottom bar on mobile | Vercel dashboard navigation redesign | Options 2, 4 and 5 move navigation or actions to a bar at the bottom on phones |
| Left nav scales to many items and is scanned faster; keep nav visible | NN/g, *Left-side vertical navigation on desktop* | Why Options 1, 2 and 5 keep nav visible at the left edge (sidebar, glass capsule, key rail) |
| Cmd+K palette for pages, records and actions, as a supplement to visible nav | Linear, Raycast `cmdk`, SaaS pattern write-ups | Options 1 and 2 put search in the top bar; a palette can sit behind it in any option (round 1's Floor tried it as the main nav, and lost) |
| Andon: read at a distance, dark background, saturated status colours, red only for urgent | Vibe andon guide; Astro UXDS status system; Vorne | Every option reserves red for expired stock; round 1's dark Control Room was dropped |
| One KPI card with hairline dividers, small sparklines | Stripe home | Option 1's figure strip: four figures in one card, not six cards |
| Calm premium: restrained palette, hairlines, generous type | Mercury (via third-party design studies; type names unconfirmed) | Option 1's spacing and neutral surfaces |
| Schedule ordered by priority; work grouped by resource or stage | Katana MRP Make screen | Option 4 groups batches into stage columns |
| Touch tiles for the front of house, dashboard for the back office | Square for Retail item grid vs Square Dashboard | Options 3 and 5 size their main controls for touch (52–68 px) |
| Reduced motion: wrap animation in a media query; never convey meaning by motion alone | web.dev, GitHub Primer | Every animated option has `prefers-reduced-motion` handling or purely decorative motion; status is always words plus colour |

Looked for and did not find: a manufacturing tool for small producers whose overview is
widely praised for its design (Katana's help docs show the schedule, not an overview).
The craft references therefore come from fintech and dev tools.

## Round 2: three replaced

The founder's first-round verdict: Control Room, Briefing and Floor were "not good". Ledger
and Flow stay. The brief for the replacements was the finer finish of the surface: glass,
soft edges, bold-but-simple. Extra research for that round:

| Pattern | Where from | What it changes here |
|---|---|---|
| Glass is a separate layer for controls and navigation; content stays underneath; too much glass distracts | Apple, *Adopting Liquid Glass* and WWDC25 sessions | Option 2 puts glass only on the nav strip, toolbar and action dock; content panels are near-opaque |
| Sidebars as a floating pane of glass; tab bar floats and can minimise | Apple Liquid Glass (macOS sidebar, iPhone tab bar), visionOS tab ornament | Option 2's vertical capsule nav floating at the left edge |
| Glassmorphism needs heavy blur and a solid-enough fill for contrast; use it sparingly | NN/g *Glassmorphism*; Axess Lab | 28 px blur, 72–80 % fills behind text; `prefers-reduced-transparency` falls back to solid |
| Users can reduce transparency and motion | Apple Liquid Glass accessibility settings | Both media queries honoured in Option 2 |
| Hierarchy from size, not weight; one accent; Swiss minimalism | Ramp brand (TWK Lausanne, regular weight, yellow CTA) | Option 3: giant numerals, a single cobalt accent, no shadows |
| Expressive design: shape, size, motion, containment; spring physics, shape morphing | Google *Material 3 Expressive* research (46 studies) | Option 3's buttons morph pill → rounded square on a spring; the current step is a scalloped "cookie" shape |
| Neumorphism fails on contrast; keep 3:1 edges for controls, labels, visible focus and pressed states | BOIA, Axess Lab, Built In | Option 5 gives every raised surface a hairline edge, full-contrast text and labelled keys; red alerts get an outline as well as colour |
| Soft rounded sheets and shadows as the craft signal | Things 3 (Apple Design Awards; 2025 refresh with more rounding and glassy buttons) | Option 5's 20–32 px radii and pressed-in current tab/key |

## Five directions

| | 1 Ledger | 2 Glass | 3 Bold | 4 Flow | 5 Soft |
|---|---|---|---|---|---|
| Idea | Calm fintech dashboard | Liquid-glass controls over a colour field | Bold yet simple, Swiss scale | Kanban board by stage | Tactile soft UI |
| Navigation | Full left sidebar, dimmed, sub-pages nested | Floating glass capsule at the left edge, glass toolbar with view tabs | Plain top text nav, active as a black pill | Floating pill nav; moves to the bottom on phone | Rail of raised keys, current key pressed in; bottom key bar on phone |
| Primary action | Indigo button, top right | Glass dock floating bottom centre | 68 px cobalt pill beside a giant 7 | Violet button, top right | Raised sage key, top right |
| Leads with | KPI strip, then one warning callout | "7 batches" and a stage ring, beside "Needs you" | A giant 7, then a black alert band | Attention chips + stage columns | A dial of batches by stage beside four alert keys |
| Batches as | Table, actions on hover | Rows with a gradient progress track | Large-type list, step pills with a scalloped current step | Cards in Just started / Middle / Final / Finished | Raised cards with a slider track and thumb |
| Type | Inter | Manrope | Bricolage Grotesque + Geist | Plus Jakarta Sans | Outfit + DM Sans |
| Colour | Warm grey, indigo | Pastel aurora, blue → cyan, ink dock | Off-white, ink, cobalt, red for expired only | Lavender, violet, coral | Warm stone, sage, apricot |
| Shape | 8–10 px radius, hairlines | 22–28 px, capsules, specular rims | Pills, 32 px band, 3 px rules, no shadows | 14–20 px, soft shadows | 20–32 px, dual light/dark shadows plus hairline |
| Motion | Sparklines draw, content rises | Slow aurora drift, ring and bars fill | Spring shape-morph on press, rows rise, current step slowly turns | Cards pop in, lift on hover | Dial arcs draw, keys press in |
| Taken from | Stripe, Mercury, Linear 2026 | Apple Liquid Glass, visionOS, NN/g | Ramp, Material 3 Expressive | Katana, Linear boards, Notion | Things 3, accessible soft UI |
| Best at | Scanning many batches at a desk | Feeling premium and current; one obvious action | Instant read: number, problem, action | Seeing flow and bottlenecks | Feeling friendly and physical; touch |
| Gives up | Personality: looks like many SaaS apps | GPU cost of blur; legibility depends on the solid fallback | Density: one batch per 80 px row | Exact age ordering; columns are coarse | Density, and soft UI dates quickly if overdone |

What all five share: Record production step is the single primary action; the 8-day
Limoncello is flagged in words and colour; expired stock is the only red; every figure the
current page shows is still reachable; phone width has no sideways scroll; all five have a
dark theme and honour `prefers-reduced-motion`.

## Decisions that are the reader's, not taste

- **Sparklines and "+3 since last Monday" (Option 1)** need a daily history of active
  batches the overview API does not return today. The mockup's line is illustrative.
- **"Finished this week" cards (Option 4)** need the finished batches' names and dates;
  the API returns only the count.
- **The stage columns (Option 4)** group by step position (first / middle / last), which
  is the only grouping the data supports without new workflow metadata.
- **Glass (Option 2)** uses `backdrop-filter` blur on every panel. It is smooth on
  current hardware, but a low-end tablet on the floor may stutter; the solid fallback
  exists for that.

## Not in this change

No template, script, stylesheet, route or API changes. No tests change. The chosen
direction will need: new design tokens (palette, type, radii) in
`app/core/frontend/css/design-system.css`, its shell (nav pattern) applied app-wide rather
than only on this page, and any new API figures listed above.

## Checks

Round 1: six passes; round 2: three more passes on the new three, then one full pass on
all five. Playwright screenshots at 1440 × 900 light and dark and 390 × 844 viewport and
full page, each read in full; the shooter fails on console
errors and on sideways scroll at every width. Defects fixed between passes are listed in
the MR.
