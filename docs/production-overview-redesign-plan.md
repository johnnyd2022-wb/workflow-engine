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
| Separate top-level menus by job; Reporting promoted to the main nav | Xero's 2025 navigation (Sales, Purchases, Tax, Reporting menus) | Option 3 puts sections behind an app switcher and a breadcrumb, leaving the bar to the view tabs |
| Left sidebar for many sections, pinned shortcuts | Stripe Dashboard (May 2024 update, shortcuts); Shopify admin nav on the left, dropdown from the title bar on mobile | Option 1 keeps a full sidebar with Production's sub-pages nested under it |
| Dim the sidebar once you have arrived; softer borders | Linear UI refresh, March 2026 ("navigation sidebar … dimmed") | Option 1's sidebar is low-contrast; the content has the only strong surfaces |
| Horizontal tabs → resizable sidebar on desktop, floating bottom bar on mobile | Vercel dashboard navigation redesign | Options 2, 4 and 5 move navigation or actions to a bar at the bottom on phones |
| Left nav scales to many items and is scanned faster; keep nav visible | NN/g, *Left-side vertical navigation on desktop* | Why Options 1, 2 and 5 keep nav visible at the left edge (sidebar, glass capsule, key rail) |
| Cmd+K palette for pages, records and actions, as a supplement to visible nav | Linear, Raycast `cmdk`, SaaS pattern write-ups | Options 1 and 2 put search in the top bar; a palette can sit behind it in any option (round 1's Floor tried it as the main nav, and lost) |
| Andon: read at a distance, dark background, saturated status colours, red only for urgent | Vibe andon guide; Astro UXDS status system; Vorne | Every option reserves red for expired stock; round 1's dark Control Room was dropped |
| One KPI card with hairline dividers, small sparklines | Stripe home | Option 1's figure strip: four figures in one card, not six cards |
| Calm premium: restrained palette, hairlines, generous type | Mercury (via third-party design studies; type names unconfirmed) | Option 1's spacing and neutral surfaces |
| Schedule ordered by priority; work grouped by resource or stage | Katana MRP Make screen | Option 4 groups batches into stage columns |
| Touch tiles for the front of house, dashboard for the back office | Square for Retail item grid vs Square Dashboard | Option 3's hero action and Option 5's phone bar are sized for touch (44–52 px) |
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
| Hierarchy from size, not weight; one accent; Swiss minimalism | Ramp brand (TWK Lausanne, regular weight, yellow CTA) | Round-2 Bold (dropped): giant numerals, a single cobalt accent, no shadows |
| Expressive design: shape, size, motion, containment; spring physics, shape morphing | Google *Material 3 Expressive* research (46 studies) | Round-2 Bold (dropped)'s buttons morph pill → rounded square on a spring; the current step is a scalloped "cookie" shape |
| Neumorphism fails on contrast; keep 3:1 edges for controls, labels, visible focus and pressed states | BOIA, Axess Lab, Built In | Round-2 Soft (dropped) gives every raised surface a hairline edge, full-contrast text and labelled keys; red alerts get an outline as well as colour |
| Soft rounded sheets and shadows as the craft signal | Things 3 (Apple Design Awards; 2025 refresh with more rounding and glassy buttons) | Round-2 Soft (dropped)'s 20–32 px radii and pressed-in current tab/key |

## Round 3: two more replaced

Bold and Soft were also rejected ("not great"). What survived so far, Ledger, Glass and Flow,
are all calm, rounded and current; what lost were strong stylisations. So round 3 looked at
what the most-praised B2B products actually ship:

| Pattern | Where from | What it changes here |
|---|---|---|
| Bento suits content with a natural hierarchy: one dominant tile, supporting tiles sized by importance, one radius and gap throughout; wide gaps read as premium | Apple product pages (teardowns), bento design guides | Option 3: a 4×2 hero for the batch that needs you most, 2×1 tiles for supporting figures, 18 px gaps, 28 px radius |
| Small tiles hold one value; bigger tiles hold richer content | Bento design guides | Each small tile is one number plus one tiny picture of it (meter, stage bars, 30-day expiry strip, week bars) |
| Product-dark: near-black with a cool tint, elevation by small lightness steps, 1 px low-contrast borders instead of shadows, a faint top-light and one accent | Linear, Vercel, Raycast (design-kit analyses; Linear's own refresh notes) | Option 5's surfaces, borders, top-light and single violet accent |
| Faint white-overlay borders (6–10 %), restrained glow behind featured elements, keycap details | Raycast (third-party extractions) | Option 5's borders, the glow behind the header, `kbd` hints on actions |
| Preview panel: step through records with ↑/↓ beside the list, open the full record from the panel | Attio table/kanban preview panel; Attio record page redesign 2026 | Option 5's detail panel with ↑ ↓ ✕ and "Open batch" |
| List-detail fits browsing many items fast when one is usually in focus; two panes, show which is open; stack on small screens | SAP Fiori, Microsoft Windows list/details, KDE HIG | Option 5 shows the selection with an accent bar; the panel drops away below 1180 px and the list stands alone on phones |

## Five directions

| | 1 Ledger | 2 Glass | 3 Bento | 4 Flow | 5 Midnight |
|---|---|---|---|---|---|
| Idea | Calm fintech dashboard | Liquid-glass controls over a colour field | One hero tile and a grid of small, sized tiles | Kanban board by stage | Product-dark list + detail |
| Navigation | Full left sidebar, dimmed, sub-pages nested | Floating glass capsule at the left edge, glass toolbar with view tabs | App switcher + breadcrumb; view tabs in the bar | Floating pill nav; moves to the bottom on phone | Linear-style sidebar with counts; bottom bar on phone |
| Primary action | Indigo button, top right | Glass dock floating bottom centre | "Record step 2" on the hero tile, for the batch waiting longest | Violet button, top right | Violet "Record step 2 (R)" in the detail panel and the bar |
| Leads with | KPI strip, then one warning callout | "7 batches" and a stage ring, beside "Needs you" | The batch waiting longest, with its step journey | Attention chips + stage columns | Four figures, alert chips, then batches grouped by stage |
| Batches as | Table, actions on hover | Rows with a gradient progress track | Compact list tile beside a product donut | Cards in Just started / Middle / Final / Finished | Dense grouped rows; selected one opens on the right |
| Type | Inter | Manrope | Onest | Plus Jakarta Sans | Inter + Geist Mono |
| Colour | Warm grey, indigo | Pastel aurora, blue → cyan, ink dock | Apple grey, white tiles, one blue | Lavender, violet, coral | Near-black (or near-white), one violet |
| Shape | 8–10 px radius, hairlines | 22–28 px, capsules, specular rims | 28 px tiles, pill buttons, 18 px gaps | 14–20 px, soft shadows | 7–12 px, 1 px borders, no shadows |
| Motion | Sparklines draw, content rises | Slow aurora drift, ring and bars fill | Tiles rise in sequence, bars and meter grow, current step pings | Cards pop in, lift on hover | Panel slides in; everything else still |
| Taken from | Stripe, Mercury, Linear 2026 | Apple Liquid Glass, visionOS, NN/g | Apple bento pages, Linear marketing | Katana, Linear boards, Notion | Linear, Raycast, Vercel, Attio |
| Best at | Scanning many batches at a desk | Feeling premium and current; one obvious action | The morning glance: what first, then everything at a look | Seeing flow and bottlenecks | Working through batches one by one, keyboard first |
| Gives up | Personality: looks like many SaaS apps | GPU cost of blur; legibility depends on the solid fallback | Batch list is capped to a tile; more scrolling on phone | Exact age ordering; columns are coarse | Needs a wide screen for the panel; dark-first may not suit everyone |

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
- **Option 3's week bars** (which day the two batches finished) need finish dates the API
  does not return; the bars are illustrative. Its trace figure (24 of 31 lines linked) and
  expiry strip come from data the API already returns.
- **Option 5's detail panel** shows started date and step history per batch; the overview
  API returns steps and start time, so this is available, but step completion dates need
  one more field.
- **Glass (Option 2)** uses `backdrop-filter` blur on every panel. It is smooth on
  current hardware, but a low-end tablet on the floor may stutter; the solid fallback
  exists for that.

## Not in this change

No template, script, stylesheet, route or API changes. No tests change. The chosen
direction will need: new design tokens (palette, type, radii) in
`app/core/frontend/css/design-system.css`, its shell (nav pattern) applied app-wide rather
than only on this page, and any new API figures listed above.

## Checks

Round 1: six passes; round 2: three passes on the new three; round 3: two passes on the
new two, then one full pass on all five. Playwright screenshots at 1440 × 900 light and dark and 390 × 844 viewport and
full page, each read in full; the shooter fails on console
errors and on sideways scroll at every width. Defects fixed between passes are listed in
the MR.
