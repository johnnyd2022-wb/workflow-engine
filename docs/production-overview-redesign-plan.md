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
| Separate top-level menus by job; Reporting promoted to the main nav | Xero's 2025 navigation (Sales, Purchases, Tax, Reporting menus) | Option 3 uses grouped top menus (Production, Stock, Sales, Compliance, Reports) instead of a sidebar |
| Left sidebar for many sections, pinned shortcuts | Stripe Dashboard (May 2024 update, shortcuts); Shopify admin nav on the left, dropdown from the title bar on mobile | Option 1 keeps a full sidebar with Production's sub-pages nested under it |
| Dim the sidebar once you have arrived; softer borders | Linear UI refresh, March 2026 ("navigation sidebar … dimmed") | Option 1's sidebar is low-contrast; the content has the only strong surfaces |
| Horizontal tabs → resizable sidebar on desktop, floating bottom bar on mobile | Vercel dashboard navigation redesign | Options 2, 4 and 5 move navigation to a bottom bar on phones |
| Left nav scales to many items and is scanned faster; keep nav visible | NN/g, *Left-side vertical navigation on desktop* | Why Options 1 and 2 use a sidebar/rail; why Option 5's hidden nav needs ⌘K and a visible tab bar to make up for it |
| Cmd+K palette for pages, records and actions, as a supplement to visible nav | Linear, Raycast `cmdk`, SaaS pattern write-ups | Option 5's command palette mixes actions ("Record production step") and batches |
| Andon: read at a distance, dark background, saturated status colours, red only for urgent | Vibe andon guide; Astro UXDS status system; Vorne | Option 2: always dark, mono numerals, red reserved for "Action required" |
| One KPI card with hairline dividers, small sparklines | Stripe home | Option 1's figure strip: four figures in one card, not six cards |
| Calm premium: restrained palette, hairlines, generous type | Mercury (via third-party design studies; type names unconfirmed) | Option 1's spacing and neutral surfaces |
| Schedule ordered by priority; work grouped by resource or stage | Katana MRP Make screen | Option 4 groups batches into stage columns |
| Touch tiles for the front of house, dashboard for the back office | Square for Retail item grid vs Square Dashboard | Option 5 is the front of house: big tiles, one tap per action |
| Reduced motion: wrap animation in a media query; never convey meaning by motion alone | web.dev, GitHub Primer | Every animated option has `prefers-reduced-motion` handling or purely decorative motion; status is always words plus colour |

Looked for and did not find: a manufacturing tool for small producers whose overview is
widely praised for its design (Katana's help docs show the schedule, not an overview).
The craft references therefore come from fintech and dev tools.

## Five directions

| | 1 Ledger | 2 Control Room | 3 Briefing | 4 Flow | 5 Floor |
|---|---|---|---|---|---|
| Idea | Calm fintech dashboard | Andon board / ops console | A written morning briefing | Kanban board by stage | Touch-first floor terminal |
| Navigation | Full left sidebar, dimmed, sub-pages nested | 64 px icon rail; bottom bar on phone | Top menus by job (Xero) | Floating pill nav; moves to the bottom on phone | Hidden: menu drawer + ⌘K palette; phone tab bar with a centre Record button |
| Leads with | KPI strip, then one warning callout | Line status ("ACTION REQUIRED") | A sentence: what matters today | Attention chips + stage columns | Three giant action tiles |
| Batches as | Table, actions on hover | Gantt timeline on one time axis | Quiet list, longest first | Cards in Just started / Middle / Final / Finished | Tiles with progress rings |
| Type | Inter | IBM Plex Sans + JetBrains Mono | Fraunces + Instrument Sans | Plus Jakarta Sans | Space Grotesk + Inter |
| Colour | Warm grey, indigo | Near-black, cyan / amber / red | Paper, forest green, clay | Lavender, violet, coral | Off-white, black, orange |
| Shape | 8–10 px radius, hairlines | 4–6 px, square, 1 px lines | Rules, no boxes | 14–20 px, soft shadows | 20–24 px, pill buttons |
| Motion | Sparklines draw, content rises | Live pulse, blinking alarm, marching current step | None | Cards pop in, lift on hover | Rings draw, palette and drawer slide |
| Taken from | Stripe, Mercury, Linear 2026 | Grafana state timeline, andon boards, Astro UXDS | Xero 2025 nav, Linear Pulse, editorial sites | Katana, Linear boards, Notion | Square POS grid, Raycast/Linear ⌘K, Vercel mobile bar |
| Best at | A laptop at a desk; scanning many batches | A TV on the wall; spotting a stuck batch | Starting the day in one read | Seeing flow and bottlenecks | A tablet on the floor; gloves, one tap |
| Gives up | Personality; looks like many SaaS apps | Light theme; less approachable for an owner at a desk | Density; scales poorly past ~15 batches | Exact age ordering; columns are coarse | Information density; nav discoverability without ⌘K |

What all five share: Record production step is the single primary action; the 8-day
Limoncello is flagged in words and colour; expired stock is the only red; every figure the
current page shows is still reachable; phone width has no sideways scroll; all five have a
dark theme (Option 2 is dark-only on purpose).

## Decisions that are the reader's, not taste

- **Sparklines and "+3 since last Monday" (Option 1)** need a daily history of active
  batches the overview API does not return today. The mockup's line is illustrative.
- **"Finished this week" cards (Option 4)** need the finished batches' names and dates;
  the API returns only the count.
- **The stage columns (Option 4)** group by step position (first / middle / last), which
  is the only grouping the data supports without new workflow metadata.
- **Hiding the navigation (Option 5)** trades discoverability for room. NN/g's guidance
  is against hidden nav on desktop; the ⌘K palette and the phone tab bar are the mitigation.

## Not in this change

No template, script, stylesheet, route or API changes. No tests change. The chosen
direction will need: new design tokens (palette, type, radii) in
`app/core/frontend/css/design-system.css`, its shell (nav pattern) applied app-wide rather
than only on this page, and any new API figures listed above.

## Checks

Five passes of Playwright screenshots (1440 × 900 light and dark, 390 × 844 viewport and
full page, 1920 × 1080 for Option 2), each read in full; the shooter fails on console
errors and on sideways scroll at every width. Defects fixed between passes are listed in
the MR.
