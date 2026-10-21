# NP3 food safety redesign

`/compliant/nz-alcohol/food-safety` (the register; NP1 and NP2 use the same page) and
`/compliant/nz-alcohol/np3-audit/check/<id>` (one check). One job for both: **am I ready for
my verifier, and what do I need to record next?**

## What is wrong today (`00-before`)

The register:
- **No h1, and the checks start low.** A dark hero comes first, then a verification panel with an always-open registration picker, then five health cards and four "live from Core" stats. The checks begin halfway down.
- **The hero contradicts the verification card.** It says "No verification visit booked" while the card directly below it says "Next verification due 24 Jan 2028".
- **Too many controls compete for attention:**
  - a rail with search, five category tabs, the CSV and PDF downloads, and an "Audit prep" box;
  - a separate "Guided next steps" panel.
- **Checks in two sections show twice.** With a filter or search on, the three checks that sit in two sections appear twice, and the tab counts double-count them.

The check page:
- **One long column, with the action buried.** The guidance drawer and reminder setting come first, then a 6-field sign-off form, then the log book, then "Connected evidence" (the same log title six times), then the history.
- **The history is hard to read.** It shows raw field keys and email addresses.
- **The status contradicts itself.** It reads "Evidence current" next to "No signed review yet".
- **The reminder setting shows to everyone.** Only admins who manage compliance can save it.
- **Log entries are cut off silently.** The log book shows 12 entries under a heading that counts them all.

## What the research changes

**MPI, NP3 Guidance (December 2025, v2)**
- Every card ends on "Show": what the verifier will ask to see. *Change:* each check leads with **What your verifier will ask to see**.
- Five topics are covered at every verification: competency and training, cleaning, hygiene and health, sourcing and tracing, and process controls. *Change:* the Verifier pack style leads with these five.
- Records must say what was done, when and by whom, and be kept for 4 years. *Change:* entries and history show date and person by name, never a raw key.

**MPI verification-frequency flowchart**
- The next verification falls 3 to 24 months out, depending on the step reached. *Change:* the verification card leads the page.

**Council guidance (Rotorua, Western Bay)**
- Most unacceptable outcomes come from missing records and corrective actions left open. *Change:* "Needs doing" lists those first.

**Comparable products**
- **Safefood 360 My Actions:** open and overdue tiles. *Change:* five readiness facts that filter the register.
- **SafetyCulture schedules:** missed and late per schedule. *Change:* the Rhythm strip.
- **Trail:** an export the inspector can find quickly. *Change:* Download sits in the header.

**Craft references**
- **Vanta controls:** OK or Needs evidence. *Change:* status tags in words.
- **Atlassian Statuspage:** a strip of daily status. *Change:* Rhythm's 12-month strip.

**Pattern guidance**
- **GOV.UK task list:** whole-row links and short status tags. *Change:* register rows.

**Looked for but not found:**
- any comparable product's first screen;
- MPI's own list of verification failure reasons;
- the allergen card's record details.

## Three directions for the register

| | Style 1: Checks | Style 2: Rhythm | Style 3: Verifier pack |
|---|---|---|---|
| Idea | Verification, five facts, Needs doing, then the register by section with whole-row checks | Every check at once, each with a 12-month strip of its records | The five mandatory topics, each with what to show and its checks, before the rest |
| Taken from | Vanta controls, GOV.UK task list, Safefood 360 | Statuspage, SafetyCulture missed/late | MPI's Know/Do/Show cards, Trail |
| Best at | Doing the next thing | Seeing which routines slip | The week before a verification |
| Gives up | History is one click away | Long; on a phone the strip shortens to 6 months | Less room for daily logging |

**Shared by all three:**
- the h1 with the programme name;
- the guidance link and Download;
- the verification card;
- the facts as filters;
- the line about records from Production;
- Needs doing;
- search;
- every check opening its own page.

**The check page:** one design for all three, because the register's style doesn't change what a single check needs.

## Changes to data

None. The Rhythm strip is built from each row's own history.

## Not in this change

- **The Food safety tab still links to `/np3-audit`, which redirects.** Fixing it needs a breadcrumb special case, so it's a follow-up.
- **One completed log entry keeps a check "ready" forever.** That's a calculation change, so it's a follow-up.
- **NP1 and NP2 still show NP3 playbook wording.**
- **`operational-verification` sits in no section.**
- **The CSV export leaves out log entries.**

## Checks

- `tests/e2e/compliant-platform/test_np3_pages.py`:
  - readiness first;
  - a search lists each check once;
  - a filter lists each check once and matches its count;
  - the verifier's list;
  - every log entry, with Show all;
  - labelled history;
  - the reminder setting shows only to managers;
  - CONCEPT ONLY widths for the three styles, and the check page at phone and laptop.
- **Screenshots, at laptop, phone, wall and dark, in each pass:**
  - the register in each style: busy, filtered and searched;
  - a check with a log, a sign-off-only check, the training register;
  - arriving from the Compliance overview.
