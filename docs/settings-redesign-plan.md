# Settings page design

Settings (`/core/settings`) lets a person maintain their account and security, choose
appearance, and reach the organisation setup they have permission to manage. Based on
fresh main `ba166c7b`, including Production !515. This draft presents three real layouts.

## What is wrong today

The six baseline screenshots show a long, undifferentiated form stack: five profile
fields fill the first screen, while two-factor status and appearance require scrolling.
Organisation links interrupt personal-account settings. Names occupy separate full-width
rows. Save buttons use the older pale treatment instead of the settled solid action.
Three notification switches look live and saved but have no persistence or API handler.
Several visible labels are not associated with their inputs. A failed profile fetch
silently leaves blank fields editable, making unavailable data look like an empty account.

## Research

Primary sources read 12 October 2026. Patterns inform our structure; their palette and
typeface are not imported. The precise three arrangements are design judgments.

| Source | Pattern | What changes here |
|---|---|---|
| [MRPeasy Settings](https://www.mrpeasy.com/resources/user-manual/settings/) | Company/system setup and user administration have distinct destinations | Organisation setup becomes its own category with existing sites/people destinations |
| [Katana Settings](https://support.katanamrp.com/en/collections/3335394-settings) | Settings groups locations, account defaults and team management | Group operational setup apart from personal contact/security forms; preserve permissions |
| [Odoo General settings](https://www.odoo.com/documentation/19.0/applications/general.html) | User, company and access configuration are distinct topics | Separate personal and organisation concerns rather than one mixed stack |
| [Linear preferences](https://linear.app/docs/account-preferences) | Personal preferences are grouped by purpose, including interface/theme | Give appearance an explicit Preferences destination; Settings desk explores focused categories |
| [Notion account settings](https://www.notion.com/help/account-settings) | Profile and account security are distinct named tasks | Use understandable category labels and keep independent forms/actions together |
| [Carbon tabs](https://www.carbondesignsystem.com/building-blocks/core/components/tabs/guidelines) | Related views can share a stable context | Settings desk shows one category with stable navigation; other concepts use jump links |
| [Carbon accordion](https://www.carbondesignsystem.com/building-blocks/core/components/accordion/guidelines) | Disclosure reduces initial density at a cost to visibility | Register shows named category summaries with native keyboard disclosure |
| [Production !515](https://gitlab.com/whistlebird/workflow-engine/-/merge_requests/515) | Title first, underlined navigation, paired cards and solid primary | Board follows the shared page rhythm, tokens, width and spacing |

Odoo's documentation index was searchable, but a full fetch failed; no unseen interface
detail is claimed. Comparative studies for these exact manufacturing Settings layouts
were not found. Settings are independent tasks, not sequential steps of one form; the
Register's hidden categories are an explicit visibility tradeoff.

## Three directions

| | Style 1: Board | Style 2: Settings desk | Style 3: Register |
|---|---|---|---|
| Idea | Profile beside organisation links; security and preferences below | Vertical category navigation with one focused category | Expandable category rows with a compact two-column profile |
| Taken from | Production !515, MRPeasy/Katana separation | Linear/Notion task grouping, Carbon related views | Carbon disclosure, Notion named account tasks |
| Best at | Familiarity and seeing the available setup at once | Completing one settings task with fewer distractions | A compact directory on a laptop or phone |
| Gives up | More initial content and scrolling | Other categories require navigation | A disclosure interaction to reveal each category |

Style 1 is closest to the selected sibling Boards. All share the same forms, values,
permissions, destinations and existing security flows. Preview `?style=1|2|3`, or use the
temporary chooser; selection persists for the browser tab without submitting edits.
Style changes preserve entered values. The chooser and two losers will be deleted after
selection. `enroll2fa` and Google-return URLs reveal security in focused/disclosed layouts.

## Shared changes

Account loading has explicit loading/unavailable/retry states. Profile editing is disabled
until real values load, preventing accidental blank edits after a failed GET. Profile
save behavior and validation remain unchanged. Associate labels with existing inputs.
Retain password, 2FA, session timeout, Google sign-in and theme behavior. Notification
switches are disabled and labelled unavailable: there is no saved preference to display.
Do not fabricate notification delivery behavior.

## Not in this change

No authentication/API/permission policy, password/2FA protocol, organisation editing,
notification delivery, integration configuration or section-settings migration. Existing
sites/people pages remain their own destinations. This is the initial presentation portion
of UX roadmap 2.5; moving integrations and section settings is still outstanding, so the
full item stays unticked. No production configuration change. The browser flows exposed duplicate profile initialization and a broken boosted return.
The existing security/session controller is now a content-loaded page controller with
request, listener, timer, fetch-wrapper and transient-element cleanup. Its security
protocol is retained; mutating requests now explicitly carry the existing CSRF token.

## Checks

Capture all three at desktop/laptop/phone/wall/dark, each category open, populated and
quiet profiles, loading, failed load/retry, a real saved edit, and boosted leave/return.
Inspect every PNG each round and finish on an empty visual defect list. Add viewport,
category visibility, draft preservation and profile-state regressions, plus a notification
availability assertion. The existing shared Settings test changes its obsolete single-stack
geometry assertions to the intentional Board while retaining links, headings and overflow.
Per the user's standing instruction, CI runs the test suite; do not wait on local pytest
or monitor CI after push. Browser screenshot flows and syntax/scanner checks run locally.

## Review round: what settings guidance says, and what changed

Reviewed against the page-design bar and two further sources found on 13 October 2026. Both rows
below come from search-result summaries of those pages; the pages themselves were not opened, so
treat them as pointers rather than quoted guidance.

| Source | Pattern | What it changes here |
|---|---|---|
| [GitLab design: saving and feedback](https://gitlab.com/gitlab-org/gitlab-design/issues/121) | Save single low-stakes fields as they change; make saving explicit for grouped or sensitive edits | Dark mode stays an instant switch; profile, password and session timeout keep their own Save |
| [Stripe Dashboard basics](https://docs.stripe.com/dashboard/basics) | Settings split into personal and business groups, each reached on its own | Supports the Settings desk: one category at a time, personal first, organisation separate |

Practitioner write-ups on settings pages also recommend a sidebar of categories once a page
is long, and an address per category so a support link can open the right place. They are
common practice, not studies.

**Recommendation: Style 2, Settings desk.** It is the only concept where the navigation does
what it looks like it does. In Style 1 the row of tabs only scrolls a 2,000px page; in Style 3
every category is closed behind a click.

Changed in all three concepts:

- The three notification switches are removed. They never saved anything, and a disabled
  control that explains it does nothing is still clutter. Preferences now holds Appearance.
- Each category has its own address (`#settings-security`), and Back returns to the last one.
- Labels and buttons are sentence case, matching the rest of the app. The "Security" card is
  named "Password", which is what it holds.
- One filled action per card: "Save session timeout", "Link Google" and "Disable 2FA" are
  outlined.

Changed in the Settings desk: the categories are the same underlined tab row that Production,
Compliance and Sales use beneath their titles, so Settings is navigated the way its sibling
sections are (the vertical list is gone). Cards are 640px wide, and first and last name share a
row, as do email and phone. On a phone the tabs are one scrolling row.
