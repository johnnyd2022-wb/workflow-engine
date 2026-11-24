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

## Round 6: Glass with the ring

The founder liked the ring in option 2's hero (one segmented circle, a figure in its middle).
Two more Glass variants make it the centre of the page. Both use only today's payload
(current step, `started_at`, the four health checks), so neither needs an API change.

| | 14 Glass D: Orbit | 15 Glass E: Halo |
|---|---|---|
| The ring shows | One arc per batch, coloured by its current step; "0 finished this week" in the middle | One arc per health check (red for expired stock); "3/4 checks clear" in the middle |
| Also | The ring's key (All 5 · Bottling 3 · Labelling & packaging 2) filters the batch list; each row has a small five-step ring | Each batch is a card with its own five-step ring, cards grouped by step |
| Navigation | Option 2's floating nav strip and action dock; phone: section switcher sheet | A's glass sidebar → icon rail → bottom tab bar |
| Best at | Seeing where every batch is, at one look | Health first, then each batch's progress |
| Gives up | A filter is one more thing to learn | Cards take more height than rows |

Checked like 11–13: each element against the viewport edge at 320, 360, 390, 900, 1280 and
1440, light and dark, with the filter and the Add to inventory sheet open. Five passes; the
last found nothing.

## Round 5: Glass refined into three variants

The founder picked Glass. These three keep its look (glass for controls, near-opaque frosted
panels for content, one blue accent, Manrope) and differ in structure. All three use the real
menus from `app/ui/page_registry.py` (Home, Production, Compliance, Sales, Settings; tabs
Overview, Planner, Workflows, Inventory; Get to work: Record production step, Add to inventory
with Manual entry / CSV upload / Barcode scan, Trace and recall; Manage production: Contract
orders, Batches, Suppliers, Production tasks, View production board) and Whistlebird Ltd's
data from `/api/core/hub/overview` on 24 Nov 2026: 5 batches under way (4 Wildflower gin, 1
Solstice gin, all at Bottling or Labelling & packaging), longest running 124 days, 2 expired
lines (Dried apple ring), 88 of 88 lines traceable, 7 workflows, 0 finished this week, 85 all time.

| | 11 Glass A: Shell | 12 Glass B: Focus | 13 Glass C: Inspector |
|---|---|---|---|
| Idea | Today's page, rebuilt in glass | One next job, then the queue | List and inspector |
| Navigation | Glass sidebar → icon rail (≤1180) → bottom tab bar (phone) | Floating ornament; phone: section switcher sheet | Sections across a top bar; phone: bottom tab bar |
| Leads with | Health and At a glance | The batch waiting longest, with its steps | The batch list grouped by step |
| Best at | Shipping first: no API change | Getting the oldest work moving | Seeing what a batch made and holds |
| Gives up | Nothing new to learn, nothing new shown | Figures are smaller and lower | Needs per-batch detail in the payload |

Production-ready details in all three: skip link, landmarks, `aria-current`, visible focus
rings, 44px targets, status in words as well as colour, Record visible on every batch (never
on hover only), Add to inventory as a menu on laptop and a bottom sheet on phone, Escape and
outside-click close, `prefers-reduced-motion` and `prefers-reduced-transparency` honoured,
and no element past the viewport at 320, 360 or 390 wide (checked per element, not only
page width). Four screenshot passes; the last found nothing.

### Decisions that are the reader's (round 5)

- **Stock lines figure.** Today's page shows `metrics.inventory_items.total`: 467 for
  Whistlebird, which counts used-up lines at zero. Lines with stock are 88
  (`inventory.nonzero_lines`). The variants show 88; the live page should too.
- **B and C need more data.** "Days at this step" needs the last completed step's
  `completed_at`, and C's inspector needs each step's date and outputs and the batch's
  stock on hand. Today's payload has only `started_at`. A uses nothing new.
- **Telling batches apart.** Four Wildflower batches are under way and the app has no batch
  code, so the variants use the start date ("Started 13 Sep").
- **Recorded quantities look odd.** Two Wildflower batches record 1 L of aged gin and then
  78 bottles. C shows this as recorded; it is worth checking at source.

## Round 4: five more, each built on one unique element

The founder asked for five more options, from design-specific sources, each unique. These sit
beside 1–5 (6–10), not instead of them. Sources: design galleries and libraries (Mobbin,
SaaSFrame, Dribbble, Behance, Awwwards, Refero, Godly), and the products those galleries keep
returning to. Galleries are image-led, so the searches mostly surfaced their commentary; the
patterns below come from the products' own guidance where it exists.

| Element | Where from | What it becomes here |
|---|---|---|
| Rings that close: three fixed goals, visual before numeric, glanceable | Apple Activity rings (HIG, Macworld interview) | 6 Rings: batch progress 35 % (8 of 23 steps), traceable 77 % (24 of 31), in date 90 % (28 of 31) |
| Widgets in small/medium/large sizes, one fact per tile | iOS home-screen widgets | 6 Rings' grid of rounded tiles |
| A multi-day timeline you scroll sideways, number keys set how many days | Notion Calendar (Cron), reviews in Efficient.app, NY Sun | 7 Calendar: 9-day grid, red now-line, mini month, "Up next"; phone becomes an agenda |
| Spaces with their own colour; the sidebar carries it as a gradient | Arc browser (Arc help centre, design guides) | 8 Spaces: All / Navy / Pink / Limoncello, page re-tints, workflow lines with batches on their step |
| Compact, glanceable progress; detail only when relevant | Apple Live Activities guidance | 8 and 10 keep each batch to one small token |
| Today list: what needs you, in order, tick to do | Things 3 (Apple Design Awards 2009, 2017) | 9 Today: 7 steps to record, 8 stock jobs (with the real untraced line names), 1 coming up |
| Progressive disclosure, calm by default, role-aware | SaaSFrame and SaaSUI 2026 dashboard write-ups | 9 shows only what needs a person; 10 hides room detail until tapped |
| A live view of the plant, by line or machine | Contra production-planning case study (per-machine load view), MES dashboards on Dribbble | 10 Floor map: steeping, still house, blending, bottling, stores |

| | 6 Rings | 7 Calendar | 8 Spaces | 9 Today | 10 Floor map |
|---|---|---|---|---|---|
| Unique element | Closing rings + widget sizes | Week timeline with now-line | Per-product colour spaces | To-do queue you tick | Distillery plan |
| Navigation | Icon-over-label tab bar at the top; bottom on phone | Rail with mini month and up-next | Gradient sidebar with pinned sections and space dots | Things-style sidebar lists with counts | Plain top bar |
| Batches as | Mini rings | Blocks on days | Tokens on workflow steps | Tasks ("Distil the Pink Gin") | Tokens in rooms |
| Best at | The 2-second glance | Seeing how long things have taken | Owners who think per product | Getting through the day | Someone walking the floor |
| Gives up | Rings need explaining once | Needs width; phone switches to agenda | Cross-product comparison | Charts and totals | Needs a station model |

### Decisions that are the reader's (round 4)

- **6 Rings' three goals** are a choice of what "healthy" means. Batch progress counts
  steps done; a goal like "steps recorded today" would need completion times.
- **7 Calendar** places blocks by real start times but spaces the steps inside a block
  evenly, because the API does not return when each step finished.
- **10 Floor map** maps steps to rooms by name. A real version needs a station (room or
  equipment) on each workflow step, which the data model does not have.

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
