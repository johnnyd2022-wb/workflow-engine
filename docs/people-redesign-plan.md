# People and roles page design

People and roles (`/core/people`, Settings › People) is where an admin invites people, changes roles, ends access, and keeps custom roles.

**What the page is for, in one sentence:** *who can get in, as what, and how do I change that?*

Part of the settings pages done together (plan 2.5). It sits under the Settings tab row from !562.

## What is wrong today

Observed in `00-before`, on main `bf069927`:

- **Wrong place in the sidebar:** it lit up Production (fixed in !562).
- **The table:** uppercase column headings ("PERSON", "ROLE", "2FA", "ACTIONS"). On a phone, the 720px minimum width hides the status and actions off to the side.
- **Roles:** "What each role can do" is a disclosure. Custom roles are a second card with nested disclosures, and their permission boxes show raw keys (`production.record`).
- **Deleting a role** used `window.confirm`.
- **Styling:** inline `<style>` in the template, with the older green primary button rather than the house one.
- **A failed load** left an empty table and a custom-roles card with nothing in it. *(Fixed: the page shows the error and Try again.)*

## What other products do

| Source | Pattern | What it changes here |
|---|---|---|
| [Linear, members](https://linear.app/docs/members-roles) (craft) | One list of members, filterable by role and status; pending invites and suspended people stay in the list; actions in the row | One list, sorted active, invited, finished, deactivated; status in words beside the role |
| [Stripe, team](https://docs.stripe.com/dashboard/teams) (craft) | Invite by email with a role chosen at once; change a role from the row later | "Invite someone" dialog keeps the role and auditor end date |
| [Katana, users](https://support.katanamrp.com/en/collections/3335394-settings) and [MRPeasy, users](https://www.mrpeasy.com/resources/user-manual/settings/) (comparable) | Users and their access are a Settings destination of their own | People is a Settings tab, not a link from Account |
| [GitLab settings study](https://gitlab.com/gitlab-org/ux-research/-/issues/1215) (pattern) | Add and edit in a modal; show less to begin with | Custom roles edit in one dialog; permissions grouped by area in plain words |
| [GOV.UK summary list](https://design-system.service.gov.uk/components/summary-list/) (pattern) | Key and value with one change action per row | Roles as rows: what it does, who has it, Edit |

**Looked for but not found:** a comparison of side-panel versus inline editing for member lists. Style 3 is a judgement.

## Three directions to choose from

| | Style 1: List | Style 2: People \| Roles | Style 3: Person panel |
|---|---|---|---|
| Idea | People, then roles, each a card of rows; role and actions in each person's row | The house view switch shows People or Roles, one at a time | A short list (name, role, status); choosing someone opens a panel with their role, status, 2FA and actions |
| Taken from | Linear members, Stripe team | Customs' view switch, Settings categories | Linear issue panel, Stripe customer detail |
| Best at | Seeing and changing everything at once | Less on screen; roles out of the way until needed | A calm list; changes only after choosing someone |
| Gives up | A long page with many controls | A switch to see roles | A click before any change |

**Shared by all three:**
- The house header with **Invite someone**.
- A summary line, for example "8 people can sign in · 1 invite waiting · 1 deactivated".
- Initials, status in words ("Invited · link expires 1 Nov 2026"), and 2FA on or off.
- One roles list showing who holds each role. Custom roles say what they start from and how many permissions they have, and open in a dialog where permissions are grouped by area in plain words.
- Deleting a role asks twice in place.
- A failed load hides the lists and offers Try again.

## Not in this change

- **APIs:** unchanged.
- **Behaviour:** invite links, the auditor end date and the server's rules are unchanged.

## Checks

- `tests/e2e/test_people_page.py`, routed into the Flask test client: a failed load leaves nothing to act on; a custom role is edited in a dialog; deleting asks twice; CONCEPT ONLY: Style 3's panel, Style 2's switch, and each layout fits at phone, laptop and wall widths.
- `test_staff_site_roles.py` (e2e) opens "New role" instead of the disclosure.
- Shots: laptop, phone, wall and dark, with a team of ten (every role, an auditor, an invite, someone deactivated, a custom role); a person open; both dialogs; a failed load; arriving by the Settings tab.

## Approved implementation — 25 Oct 2026

Style 2 (People | Roles) is the approved design for !565. The experimental layout selector and the discarded layouts have been removed.

Validation: 9 browser cases passed, covering the page actions and responsive layouts. Security scan of the changed app files passed.
