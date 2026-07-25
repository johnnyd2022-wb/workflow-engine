# AGENTS.md — Operating Instructions for this Workspace

Read this before acting as any skill in this workspace. It applies to every agent, human-
or trigger-invoked.

## Read order

1. `context/operating-principles.md` — the rules of the road.
2. `context/founder.md` — who you're working for, capacity, comms style.
3. The specific `skills/<skill>/SKILL.md` you're acting as.
4. The context files that skill's "Inputs" section names (business facts, brand, audiences,
   pricing).
5. The relevant `projects/<business>/*.md` — the current source of truth.

## Non-negotiables

- **Don't invent facts.** If a number, date, or status is missing, state your assumption
  explicitly or ask. Several figures in `context/` are marked "verify" — respect that.
- **Protect proprietary information**, especially Whistlebird botanical recipes/
  formulations. Manage process structure, never expose the formula.
- **Keep the two brands distinct.** Whistlebird = spirits brand; Biz-E = SaaS. Share
  founder credibility, never blur voices or audiences.
- **Respect the Claude-PM / Biz-E boundary.** If work becomes a repeatable operational
  workflow, recommend moving execution into Biz-E rather than managing it here forever.

## Output contract (every skill, every time)

- Lead with the recommendation. Be direct and practical.
- Produce a **structured markdown artifact** using the skill's template where one exists.
- **End with concrete next actions — owner + date** wherever possible.
- Convert decisions → tasks → schedules → follow-ups.
- Name the **handoff**: which skill/tool should consume this output next.

## Where things live (source of truth)

| Domain | Source of truth |
|---|---|
| Whistlebird / Biz-E projects | `projects/**` markdown in this workspace |
| Biz-E code & features | the Biz-E repo + GitLab + its own `AGENTS.md` |
| Generated weekly/quarterly artifacts | `outputs/` |

## Handoff conventions

Skills pass **artifacts**, not function calls. Standard chains:

- Project brief → marketing brief → content pack → sales sequence → task list.
- Feature release → release notes → changelog → marketing brief → content pack → sales
  email → CRM follow-up.

Use the shared contracts (in each skill's `templates/`) so the next skill can consume the
output without rework.

## Tooling notes

- GitLab: use `glab`; username `johnnyd2022`; assign MRs to `johnnyd2022`.
- Gmail: connected via MCP tools as **sales@whistlebird.co.nz**. Email-facing skills
  (Sales Watches, Outbound Sales, and anyone drafting email) **only create drafts —
  never send**. The founder reviews and sends from Gmail. Calibrate tone from our sent
  mail (`in:sent`) before drafting; no AI voice (no em-dashes, no "I hope this finds you
  well", no corporate filler).
- Slack: connected as the founder. When a skill finishes a deliverable — a plan, a content
  pack, a pipeline review, a weekly command centre — post a short FYI to the `general`
  channel in `.agents/notifications.json`: what was produced, where it lives, and the one
  thing worth deciding. Announce it, don't paste it. **Never post the contents when they
  name a customer, carry pricing, or were drafted for an external recipient** — those stay
  in the file for the founder to open. Drafts-only is unchanged: this announces that a
  draft exists, it never sends one. Resolve the connector's tool name at runtime, and if
  Slack is unavailable just say so in the report rather than failing the run.
- Dates: NZ context; today's date is provided by the session. Convert relative dates
  ("next Tuesday") to absolute dates in artifacts.
- Default to markdown. Don't reach for heavier systems unless complexity demands it.
