#!/usr/bin/env python3
"""Generate one cofounder-friendly HTML page per Founder Ops skill."""
import os

OUT = os.path.dirname(os.path.abspath(__file__))  # pages land next to this script

ACCENTS = {
    "wb":   ("#2B7A55", "#EAF4EE", "Whistlebird"),
    "bize": ("#2B5F8E", "#EAF0F8", "Biz-E"),
    "both": ("#1E7A7A", "#E6F4F4", "Both businesses"),
}

CSS = """
  :root {{
    --ink:#182435; --text:#374151; --muted:#6B7B8D; --ground:#F5F6F8;
    --surface:#FFFFFF; --rule:#DDE1E8; --accent:{accent}; --accent-tint:{tint};
    --red:#B33030; --red-tint:#FDECEA; --amber:#9A6318; --amber-tint:#FAF3E6;
  }}
  *, *::before, *::after {{ box-sizing:border-box; }}
  body {{ background:var(--ground); color:var(--text);
    font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif;
    font-size:15px; line-height:1.65; margin:0; }}
  .page {{ max-width:760px; margin:0 auto; padding:44px 32px 80px; }}
  .eyebrow {{ font-size:10.5px; font-weight:700; letter-spacing:.14em;
    text-transform:uppercase; color:var(--accent); margin:0 0 10px; }}
  h1 {{ font-family:Georgia,'Times New Roman',serif; font-size:27px; font-weight:normal;
    color:var(--ink); line-height:1.28; margin:0 0 10px; text-wrap:balance; }}
  .tagline {{ font-size:15.5px; color:var(--muted); margin:0 0 34px; line-height:1.55; }}
  .summary-box {{ background:var(--ink); color:#CBD8E6; border-radius:5px;
    padding:22px 26px; margin-bottom:40px; font-size:14.5px; line-height:1.72; }}
  .summary-box p {{ margin:0; }}
  .summary-box strong {{ color:#E2EAF2; font-weight:600; }}
  .summary-label {{ font-size:9.5px; font-weight:700; letter-spacing:.14em;
    text-transform:uppercase; color:#7FB8A4; margin:0 0 8px; }}
  .section {{ margin-bottom:42px; }}
  .section-label {{ font-size:10px; font-weight:700; letter-spacing:.16em;
    text-transform:uppercase; color:var(--muted); margin:0 0 16px;
    padding-bottom:9px; border-bottom:1px solid var(--rule); }}
  .chips {{ display:flex; gap:8px; flex-wrap:wrap; }}
  .chip {{ background:var(--accent-tint); color:var(--accent); padding:7px 15px;
    border-radius:100px; font-size:13px; font-weight:600; line-height:1.4; }}
  .get-list {{ list-style:none; margin:0; padding:0; display:flex;
    flex-direction:column; gap:10px; }}
  .get-item {{ background:var(--surface); border:1px solid var(--rule);
    border-radius:4px; padding:15px 18px; }}
  .get-item strong {{ display:block; font-size:14.5px; color:var(--ink); margin-bottom:3px; }}
  .get-item span {{ font-size:13px; color:var(--muted); line-height:1.6; }}
  .not-list, .know-list {{ list-style:none; margin:0; padding:0; display:flex;
    flex-direction:column; gap:8px; }}
  .not-list li {{ display:flex; gap:12px; align-items:flex-start; padding:12px 16px;
    background:var(--red-tint); border-left:3px solid var(--red);
    border-radius:0 4px 4px 0; font-size:13.5px; line-height:1.6; }}
  .not-list li::before {{ content:"✕"; color:var(--red); font-size:12px;
    font-weight:700; flex-shrink:0; margin-top:2px; }}
  .not-list em {{ font-style:normal; color:var(--muted); }}
  .know-list li {{ display:flex; gap:12px; align-items:flex-start; padding:12px 16px;
    background:var(--surface); border-left:3px solid var(--accent);
    border:1px solid var(--rule); border-left:3px solid var(--accent);
    border-radius:0 4px 4px 0; font-size:13.5px; line-height:1.6; }}
  .know-list li::before {{ content:"●"; color:var(--accent); font-size:9px;
    flex-shrink:0; margin-top:6px; }}
  .foot {{ font-size:12px; color:var(--muted); border-top:1px solid var(--rule);
    padding-top:16px; line-height:1.6; }}
  .foot code {{ font-family:'SF Mono',Menlo,monospace; font-size:11px;
    background:var(--surface); border:1px solid var(--rule); border-radius:3px;
    padding:1px 5px; }}
  .group-table {{ width:100%; border-collapse:collapse; font-size:13.5px; }}
  .group-table td {{ padding:10px 14px 10px 0; border-bottom:1px solid var(--rule);
    vertical-align:top; }}
  .group-table td:first-child {{ font-weight:600; color:var(--ink);
    white-space:nowrap; padding-right:20px; }}
  h2 {{ font-family:Georgia,serif; font-size:17px; font-weight:normal;
    color:var(--ink); margin:0 0 12px; }}
  @media (max-width:600px) {{ .page {{ padding:32px 20px 60px; }} h1 {{ font-size:22px; }} }}
"""

def wrap_document(title, css, body):
    """Full standalone HTML5 document: doctype/head/charset/viewport, so pages
    render correctly (no mis-decoded em-dashes/curly-quotes/bullets, no quirks
    mode) whether opened directly as a file, served, or turned into an artifact."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>{css}</style>
</head>
<body>
{body}
</body>
</html>
"""

def render(s):
    accent, tint, biz_label = ACCENTS[s["business"]]
    css = CSS.format(accent=accent, tint=tint)
    chips = "\n".join(f'      <span class="chip">{c}</span>' for c in s["use_when"])
    gets = "\n".join(
        f'      <li class="get-item"><strong>{t}</strong><span>{d}</span></li>'
        for t, d in s["outputs"])
    nots = "\n".join(
        f'      <li><span>{item} <em>→ {who}</em></span></li>'
        for item, who in s["not_do"])
    knows = "\n".join(f'      <li><span>{k}</span></li>' for k in s["good_to_know"])
    body = f"""<div class="page">
  <header>
    <p class="eyebrow">Founder Ops Skill · {biz_label}</p>
    <h1>{s['title']}</h1>
    <p class="tagline">{s['tagline']}</p>
  </header>

  <div class="summary-box">
    <p class="summary-label">What it does</p>
    <p>{s['summary']}</p>
  </div>

  <section class="section">
    <p class="section-label">Use it when</p>
    <div class="chips">
{chips}
    </div>
  </section>

  <section class="section">
    <p class="section-label">What it gives you</p>
    <ul class="get-list">
{gets}
    </ul>
  </section>

  <section class="section">
    <p class="section-label">What it deliberately stays out of</p>
    <ul class="not-list">
{nots}
    </ul>
  </section>

  <section class="section">
    <p class="section-label">Good to know</p>
    <ul class="know-list">
{knows}
    </ul>
  </section>

  <p class="foot">Part of the Founder Ops workspace — a library of 16 playbooks Claude can
  act as. The full playbook behind this page lives at <code>skills/{s['slug']}/SKILL.md</code>.
  Every skill follows the same ground rules: never invent facts, protect the Whistlebird
  recipes, keep the two brands' voices separate, and end every output with concrete next
  actions (owner + date).</p>
</div>"""
    return wrap_document(f"{s['title']} — Founder Ops Skill", css, body)

SKILLS = [
 dict(n="01", slug="business-operator", business="both",
  title="Business Operator — the Chief of Staff",
  tagline="Decides what matters most this week across both businesses, and routes everything else to the right specialist.",
  summary="The top-level playbook — the one to start each week with. It reads across both businesses (active projects, sales pipelines, content calendars, upcoming deadlines), weighs it all against the founder time that actually exists, and picks the <strong>three things that matter most this week</strong>. Each priority is routed to the right specialist skill, and the output always ends with one concrete action for tonight.",
  use_when=["Monday / start-of-week planning", "“What should I work on next?”", "Feeling overwhelmed or pulled in every direction", "Two businesses competing for the same evening"],
  outputs=[
   ("Weekly Command Centre", "A one-page brief: top 3 priorities, what can safely wait, per-business status, risks, and a schedule that fits real capacity."),
   ("Tonight's next action", "One concrete task, 30 minutes or less — so a busy evening still moves something forward."),
   ("Explicit handoffs", "Each priority is passed to a specialist skill (e.g. “Sales Manager: draft 4 reorder follow-ups”), so the next session can act without re-explaining.")],
  not_do=[
   ("Doing the specialist work itself — it routes, it doesn't write emails or plans", "the specialist skills"),
   ("Repeatable production, inventory or compliance records", "the Biz-E product"),
   ("Hour-by-hour scheduling of the week", "Calendar Planner")],
  good_to_know=[
   "It deliberately over-protects the two things that slip first under time pressure: <strong>sales follow-ups</strong> and <strong>marketing consistency</strong>.",
   "It never plans more hours than exist — if capacity is unknown, it asks instead of guessing.",
   "If everything feels urgent, it cuts to the three things that move revenue or a hard deadline, and defers the rest explicitly rather than silently dropping them."]),

 dict(n="02", slug="project-manager", business="both",
  title="Project Manager",
  tagline="Turns a goal into a lightweight plan — milestones, risks, and always-current next actions.",
  summary="For one-off “change” work: a product launch (like Green Gold), the liquor licence, a new Biz-E feature, a website build. It creates a deliberately small plan — <strong>3–7 milestones</strong>, each with a due date and a clear “done” test — tracks the top risks with real mitigations, and reports weekly as <strong>Done / Blocked / Next</strong>. Enough structure to make progress visible, never so much that the plan becomes the work.",
  use_when=["Kicking off a launch or project", "Weekly project check-in", "“Are we on track?”", "Something has slipped or is blocked"],
  outputs=[
   ("Project brief", "A single page per project: objective, business value, milestones, dependencies, and target date."),
   ("Timeline & risk register", "A simple Gantt view sized to real evenings, plus the top 3 risks each with a concrete mitigation — not just a worry."),
   ("Weekly update", "Done / Blocked / Next, ending with next actions that each have an owner and a date.")],
  not_do=[
   ("Repeatable operations once a launch becomes routine production", "the Biz-E product"),
   ("Strategy calls — what to launch and why", "Distillery Strategy Advisor / Biz-E Product Manager"),
   ("Writing the marketing, sales or content assets", "Marketing Director → Content Producer")],
  good_to_know=[
   "Plans are sized to the founder's real availability — never a fantasy full-time schedule.",
   "If a milestone has no clear “done” test, it gets sharpened or cut.",
   "Blockers are surfaced the moment they appear, not saved up for the weekly update."]),

 dict(n="03", slug="calendar-planner", business="both",
  title="Calendar Planner",
  tagline="Places the week's priorities into the hours that actually exist.",
  summary="Takes the week's top 3 (from the Business Operator) plus any due follow-ups, and builds a realistic, time-blocked week around the fixed constraints: the day job, family evenings, distillery nights. If everything doesn't fit — and it often doesn't — it <strong>says so honestly</strong> and recommends what to defer, instead of pretending an impossible week is fine.",
  use_when=["“Plan my week”", "“When am I actually doing this?”", "Planning tonight", "Too much to fit and something has to give"],
  outputs=[
   ("Time-blocked weekly schedule", "Each priority placed into a specific, realistic window — hard/creative work into high-energy slots, admin into tired ones."),
   ("Follow-ups on named days", "Every sales follow-up and project action lands on a specific day — never “sometime this week”."),
   ("Explicit trade-offs", "When the week is over-committed, a clear recommendation of what to defer, sent back to the Business Operator.")],
  not_do=[
   ("Choosing what the priorities are — it places them, it doesn't pick them", "Business Operator"),
   ("Doing the work inside the blocks", "the specialist skills"),
   ("Managing the day-job meeting calendar", "the day job's own systems")],
  good_to_know=[
   "It never schedules more hours than exist — it under-fills rather than over-promises.",
   "Family and rest time is protected by default; evenings are treated as short, interruptible blocks unless told otherwise.",
   "Small consistent blocks for sales and marketing beat one big heroic block that never happens."]),

 dict(n="04", slug="finance-advisor", business="both",
  title="Finance Advisor",
  tagline="Keeps margins, cashflow and subscription revenue visible, so time-and-money decisions are made with open eyes.",
  summary="Lightweight, decision-oriented finance — not bookkeeping. For Whistlebird: bottle and case margins, channel profitability, pricing sanity-checks (e.g. working back a wholesale price from Green Gold's $30 shelf target). For Biz-E: monthly recurring revenue and progress toward targets. Every number is <strong>labelled with its assumption</strong> and what needs verifying in Xero before anyone relies on it.",
  use_when=["Weekly finance check", "“Can we afford this?”", "Setting or changing a price", "A margin or cashflow question"],
  outputs=[
   ("Weekly finance summary", "Revenue trend, margins, upcoming obligations, the one cash risk that matters most — and one clear recommendation."),
   ("Margin analysis", "Bottle/case economics or Biz-E cost-to-serve, with every assumption stated and sensitivity shown (e.g. “if costs rise 5%…”)."),
   ("Decision support", "Frames spending and time decisions against agreed thresholds, with a “confirm first” flag when a number isn't verified.")],
  not_do=[
   ("Bookkeeping, tax and statutory accounts", "the accountant + Xero"),
   ("Setting prices or terms — it recommends, the founder decides", "founder"),
   ("Product and go-to-market strategy", "Strategy Advisor / Biz-E PM / Marketing Director")],
  good_to_know=[
   "It refuses to present an estimate as a booked figure — planning numbers are always marked as such.",
   "Reorders and customer retention are treated as cheaper than new revenue, and recommendations reflect that.",
   "Anything with tax or statutory implications gets deferred to the accountant, not advised on."]),

 dict(n="05", slug="marketing-director", business="both",
  title="Marketing Director",
  tagline="Decides what to say, to whom, on which channel — then writes the brief so content gets made without guessing.",
  summary="Owns positioning, the content calendar and campaign planning for both brands. It turns a business event — an award win, a release like Green Gold, a season like Christmas gifting — into a focused campaign: <strong>one audience, one message, one to three channels</strong>. The key output is a tight marketing brief that the Content Producer can turn into finished assets without guessing.",
  use_when=["Something worth promoting happens", "Weekly content planning", "A launch needs a marketing plan", "The calendar has gone quiet"],
  outputs=[
   ("Campaign plan & content calendar", "A realistic, seasonally-aware calendar sized to founder capacity — a steady cadence, not unsustainable bursts."),
   ("Marketing briefs", "The handoff document: audience, objective, one key message, proof points, call-to-action, channels, deadline."),
   ("Channel & asset list", "What's needed to run the campaign (photos, links, screenshots) and where each piece will go.")],
  not_do=[
   ("Writing the finished posts, newsletters and copy", "Content Producer"),
   ("Sales outreach and pipeline work — it enables, they sell", "Sales Manager"),
   ("Inventing product facts, prices or award claims", "the shared fact files — if missing, it asks")],
  good_to_know=[
   "One message per asset — if it needs two messages, it becomes two assets.",
   "It guards the brand voices: Whistlebird is warm, craft-led and local; Biz-E is direct and pain-led with zero buzzwords. Never blurred.",
   "It prefers a sustainable weekly rhythm over a big one-off campaign that won't repeat."]),

 dict(n="06", slug="content-producer", business="both",
  title="Content Producer",
  tagline="Turns a marketing brief into publish-ready posts, newsletters and copy — in the right brand voice.",
  summary="The writer. Given a marketing brief, it produces finished, publish-ready assets — LinkedIn, Instagram and Facebook posts, newsletters, website and product-page copy — with <strong>two variants for the main channel</strong> and clear calls-to-action. The goal: publishing takes minutes of review, not an evening of writing.",
  use_when=["A marketing brief exists and assets are needed", "Repurposing one piece into many (blog → 3 posts)", "Website or product-page copy", "An announcement needs words, fast"],
  outputs=[
   ("Complete content pack", "Every asset the brief asked for, drafted to each channel's format and length, in the correct brand voice."),
   ("Variants & CTA options", "Two versions of the primary asset plus alternative calls-to-action, so there's always a choice."),
   ("Blockers list", "Anything still needed before publishing (photo, screenshot, link) is flagged explicitly — nothing ships half-done.")],
  not_do=[
   ("Strategy, audience and channel choices", "Marketing Director"),
   ("Sales outreach sequences (though it supplies snippets)", "Sales Manager"),
   ("Inventing facts, prices, awards or ABVs — it flags gaps instead", "the shared fact files")],
  good_to_know=[
   "It never claims an unshipped feature — anything not live is written as “in progress”.",
   "The two brands' voices stay strictly separate, even when producing for both in one sitting.",
   "One idea per asset; if a brief tries to say two things, it produces two assets or asks which message wins."]),

 dict(n="07", slug="sales-manager", business="both",
  title="Sales Manager",
  tagline="Makes follow-up effortless — decides who to contact next and drafts the message so you just review and send.",
  summary="Keeps revenue moving by protecting the thing that slips first: consistent follow-up. It reviews both pipelines, flags <strong>reorders due</strong> (Whistlebird stores restock roughly every 3 weeks) and stalled conversations, prioritises who to contact and why, and <strong>drafts the actual messages</strong> — in the right register for bottle stores, distributors, hospitality, or Biz-E prospects.",
  use_when=["Weekly sales review", "Reorders coming due", "A deal has gone quiet", "New outreach — e.g. pitching Green Gold to existing stockists"],
  outputs=[
   ("Next-best-action list", "Who to contact this week, in priority order, with the reason for each."),
   ("Ready-to-send drafts", "Follow-ups, pitches and reorder nudges with the right name, context, one clear ask and one call-to-action."),
   ("Pipeline summary", "Stage counts, stalled deals, reorders due — and a follow-up date on every live opportunity.")],
  not_do=[
   ("Marketing campaigns and positioning", "Marketing Director"),
   ("Changing prices or trade terms — it flags, never commits", "founder + Finance Advisor"),
   ("Record-keeping as a system", "CRM Updater")],
  good_to_know=[
   "Reorders beat new customers — an existing stockist reordering is the cheapest revenue there is.",
   "A deal without a next-touch date is treated as a leak; every active opportunity gets one.",
   "Objection-handling scripts exist for both businesses — margin questions for retailers, “isn't this just another ERP?” for Biz-E."]),

 dict(n="08", slug="crm-updater", business="both",
  title="CRM Updater",
  tagline="Keeps the pipeline records true after every email, call and demo.",
  summary="The hygiene counterpart to the Sales Manager: one decides and drafts, this one <strong>records and maintains</strong>. After any sales interaction it updates the contact's stage, logs what happened in one line, sets the next follow-up date, and sweeps for anything going stale — so that when priorities are set, they're set from reality, not memory.",
  use_when=["After an email, call, demo or order", "Weekly stale-lead sweep", "“Log this interaction”", "The pipeline feels out of date"],
  outputs=[
   ("Updated pipeline records", "Stage, last touch, a one-line factual note, and the next follow-up date — for every contact touched."),
   ("Follow-up tasks", "Dated tasks handed to the Sales Manager to action."),
   ("Stale-pipeline report", "Everyone past their follow-up date or untouched for 2+ weeks, so nothing silently rots.")],
  not_do=[
   ("Deciding who to contact or what to say", "Sales Manager"),
   ("Writing outreach content", "Sales Manager / Content Producer"),
   ("Pricing and terms", "founder + Finance Advisor")],
  good_to_know=[
   "Cardinal rule: <strong>no active contact without a next-action date.</strong>",
   "Whistlebird's ~3-week reorder cycle sets reorder follow-up dates automatically.",
   "Notes stay factual and short — it never editorialises or invents outcomes, and never changes a deal stage without evidence."]),

 dict(n="09", slug="distillery-strategy-advisor", business="wb",
  title="Distillery Strategy Advisor",
  tagline="Whistlebird's strategy brain — what to make, when to release it, where to sell it, which awards to chase.",
  summary="For the big Whistlebird calls: new products (Green Gold, the liqueur range), seasonal release timing, awards strategy, retail expansion, events and tastings. It lays out the options, <strong>scores them on a decision matrix</strong> (brand fit, margin, distinctiveness, effort, risk), and recommends one — then turns a “go” into a launch brief ready for the Project Manager.",
  use_when=["“Should we launch X?”", "Planning the release calendar", "Choosing which awards to enter", "Retail expansion or event planning"],
  outputs=[
   ("A clear recommendation", "One pick with the reasoning and the biggest risk — a decision, not an options dump."),
   ("Product decision matrix", "Options scored side-by-side on the things that matter: brand fit, margin, award potential, seasonality, complexity, cash risk."),
   ("Launch brief", "A “go” becomes a ready-to-plan brief covering the full launch spine — recipe lock through label, costing, content and outreach.")],
  not_do=[
   ("The secret botanical recipes — never surfaced, never inferred, ever", "the founder, privately"),
   ("Running production, inventory or compliance records", "the Biz-E product"),
   ("Executing the launch day-to-day", "Project Manager")],
  good_to_know=[
   "Timing is seasonal by design — gifting season, weddings, Dry July, awards windows all factor in.",
   "It works at concept and structure level only; formulas and exact processes stay private with the founder.",
   "Every “go” becomes a plan with milestones — enthusiasm alone doesn't ship products."]),

 dict(n="10", slug="compliance-project-assistant", business="wb",
  title="Compliance Project Assistant",
  tagline="Keeps licence and label work from slipping — tracks requirements, evidence and deadlines, and drafts the paperwork.",
  summary="Runs regulatory projects — like the current off-licence application — as organised, deadline-driven trackers. It captures the official requirements, maintains the evidence checklist and the <strong>missing-items list</strong>, keeps the critical deadline loud, and drafts communications for the founder to review, verify and send. It organises and drafts; it does <strong>not</strong> give legal advice.",
  use_when=["Liquor licence application work", "Label approval for a new product (e.g. Green Gold)", "A regulator deadline is approaching", "Gathering evidence for a submission"],
  outputs=[
   ("Compliance tracker", "Every requirement traced to its official source: what's needed, who owns it, status, evidence, due date."),
   ("Missing-items list & timeline", "What still blocks submission, and a timeline with the critical deadline highlighted."),
   ("Draft communications", "Letters and emails to regulators or partners, clearly marked “draft — founder to review and verify”.")],
  not_do=[
   ("Legal interpretation, advice, or certifying compliance", "the founder + official sources / professional advisors"),
   ("Ongoing production compliance records once operations are routine", "the Biz-E product"),
   ("General project scheduling beyond the compliance work", "Project Manager")],
  good_to_know=[
   "It never asserts a legal requirement it can't cite from the official source — unknowns are flagged “confirm”, not guessed.",
   "Deadlines are surfaced early and repeatedly; a submission date at risk escalates immediately.",
   "It's currently the engine behind the liquor licence project (off-licence with remote-seller endorsement + duty manager's certificate)."]),

 dict(n="11", slug="bize-product-manager", business="bize",
  title="Biz-E Product Manager",
  tagline="Decides what Biz-E builds next and why — grounded in real customer pain, not ideas.",
  summary="Turns customer conversations and observed pain — 20-hour audit prep, spreadsheet chaos, traceability gaps — into crisp product decisions: what to build, the <strong>smallest version worth building</strong>, what's explicitly out of scope, and how success will be measured. Keeps the roadmap prioritised with reasoning a small team can act on.",
  use_when=["“Should we build this?”", "Scoping a feature before build", "Prioritising the roadmap", "After customer feedback or a lost deal"],
  outputs=[
   ("PRDs & feature briefs", "The problem in the customer's words, target user, scope in/out, acceptance criteria, success metrics, risks."),
   ("Prioritised roadmap", "Ranked with the value / effort / strategic-fit reasoning visible — not just an ordered list."),
   ("Problem statements", "Customer pain captured as evidence (“As an operator, I can't X, so Y”), ready to design against.")],
  not_do=[
   ("How to build it — architecture and data models", "CTO / Software Architect"),
   ("Shipping mechanics and release readiness", "Release Manager"),
   ("Go-to-market messaging and selling", "Marketing Director / Sales Manager")],
  good_to_know=[
   "It builds only against evidenced pain — if evidence is thin, it proposes a discovery step, not a build.",
   "It protects the moat: user-configurable processes (the process graph), compliance and traceability beat cosmetic features.",
   "Scope gets cut before dates move — ship a thin slice and learn."]),

 dict(n="12", slug="cto-software-architect", business="bize",
  title="CTO / Software Architect",
  tagline="The skeptical senior engineer — challenges designs before they're built, and records the decisions so they stick.",
  summary="Reviews Biz-E's technical plans <strong>before</strong> code gets written: architecture, data model, security and operational risk. Its special obsession is keeping each customer's data fully isolated from every other customer's. Decisions get recorded in short decision documents (ADRs), and every review ends with an unambiguous verdict: <strong>approve, approve-with-conditions, or rework</strong>.",
  use_when=["Before building anything significant", "A security-sensitive change (logins, tokens, integrations like Xero)", "Reviewing a design or data model", "Deciding what technical debt to pay down"],
  outputs=[
   ("A structured review with a verdict", "Approve / approve-with-conditions / rework — with testable conditions and owners, never a vague maybe."),
   ("Decision records (ADRs)", "The context, options considered, decision and consequences — so choices survive and don't get re-litigated."),
   ("Risk, testing & monitoring plan", "Security and data risks with severities, plus how the change will be tested and observed in production.")],
  not_do=[
   ("Deciding what to build or its priority", "Biz-E Product Manager"),
   ("Release mechanics — checklists, changelogs, rollback execution", "Release Manager"),
   ("Scheduling the build", "Project Manager")],
  good_to_know=[
   "Customer-data isolation is non-negotiable — any design that could leak data across customers is blocked outright.",
   "It prefers boring, reversible choices that one person can operate — simplicity over cleverness.",
   "Secrets and tokens live encrypted in the database, never in browser cookies — a standing rule from the Xero integration."]),

 dict(n="13", slug="release-manager", business="bize",
  title="Release Manager",
  tagline="The gate between “merged” and “in customers' hands” — ships safely, then makes sure nothing ships silently.",
  summary="Before a release: runs the safety checklist — tests green, database changes reversible, rollback plan written, monitoring ready — and issues a clear <strong>go / no-go</strong>. After: writes the internal release notes and a <strong>plain-language customer changelog</strong>, then triggers the marketing brief and sales enablement note so shipped value actually reaches customers and the sales pipeline.",
  use_when=["A feature is merged or tagged", "“Ship it”", "Preparing a customer-facing announcement", "Something needs rolling back"],
  outputs=[
   ("Release readiness report", "A clear go or no-go with named blockers — never a maybe."),
   ("Release notes + customer changelog", "Technical notes for the record, and a customer version written as value (“what you can now do”), not a code diff."),
   ("Downstream handoffs", "For anything customer-visible: a marketing brief stub, a sales enablement note, and a post-release watch list.")],
  not_do=[
   ("Architecture and design decisions — it enforces the CTO's gates", "CTO / Software Architect"),
   ("Deciding what gets built", "Biz-E Product Manager"),
   ("Writing the finished marketing content", "Marketing Director → Content Producer")],
  good_to_know=[
   "Automatic no-go if a database change can't be rolled back, monitoring can't detect the main failure, or a security gate is unmet.",
   "Nothing ships silently: every customer-visible change gets a changelog entry, and the marketing/sales handoff is mandatory.",
   "It describes honestly — partial features are marked “beta / rolling out”, never oversold."]),

 dict(n="14", slug="customer-success-onboarding", business="bize",
  title="Customer Success & Onboarding",
  tagline="Gets a manufacturer from spreadsheets to their first working process — fast — and keeps them succeeding after.",
  summary="Makes Biz-E easy to adopt and hard to leave. It captures a prospect's real-world process, identifies the <strong>first process to model</strong> (the one that relieves the most pain fastest), builds an onboarding plan with a dated first-value milestone, scripts demos around <em>their</em> workflow rather than a generic tour, and runs health checks so at-risk customers are spotted early.",
  use_when=["A deal is won", "A demo is booked", "A support question arrives", "Periodic customer health check"],
  outputs=[
   ("Onboarding plan", "Milestones from signup → first modelled process → live use, with a dated time-to-first-value target."),
   ("Tailored demo script", "Opens on their sharpest pain (“audit prep shouldn't take 20 hours”), then shows their own process traced end-to-end."),
   ("Support material & health checks", "Setup checklists, training notes, FAQs, drafted support replies, and green/amber/red account ratings with reasons.")],
  not_do=[
   ("Selling, pricing and closing", "Sales Manager"),
   ("Deciding what the product does next", "Biz-E Product Manager — it feeds adoption friction back as evidence"),
   ("Fixing bugs — it triages and drafts the customer holding reply", "engineering (CTO)")],
  good_to_know=[
   "North star: time-to-first-value — one working process beats a complete configuration.",
   "It speaks the operator's language (audit stress, spreadsheet chaos), never feature lists.",
   "It never promises unshipped features, and feature gaps go back to the Product Manager as discovery evidence."]),

 dict(n="15", slug="sales-watches", business="both",
  title="Sales Watches — Inbox Triage & Reply Drafting",
  tagline="Reads the sales inbox, works out what needs a reply, and leaves the reply drafted in Gmail — in the founder's own voice. It never sends.",
  summary="Connected to the <strong>sales@whistlebird.co.nz</strong> Gmail account, it scans recent mail, separates the threads that genuinely need a reply from the noise, and writes the reply <strong>as a Gmail draft</strong> — so clearing the inbox becomes review-and-send, not compose-from-scratch. Before writing anything it reads our own recent sent mail and copies the real tone: greeting, sign-off, sentence length. The cardinal rule is absolute: <strong>it never sends an email</strong> — every draft waits in Gmail for the founder.",
  use_when=["“Check my email” / start-of-day triage", "Catching up after a few days away", "A busy week means replies are slipping", "Making sure no stockist or customer email sits unanswered"],
  outputs=[
   ("Reply drafts in Gmail", "One draft per thread that needs it, on the right thread, in the founder's voice, with anything unverified marked “[CONFIRM: …]” rather than guessed."),
   ("Inbox triage report", "One screen: what was drafted, what needs a founder decision, what's just FYI, and who we're waiting on — each with a one-line reason."),
   ("Chase list", "Threads where we asked and they've gone quiet, dated and handed to the Sales Manager.")],
  not_do=[
   ("Sending email — ever. Every draft is reviewed and sent by the founder", "founder"),
   ("Cold first-touch outreach to new contacts", "Outbound Sales"),
   ("Deciding pipeline strategy or who to proactively chase", "Sales Manager"),
   ("Licence / regulator correspondence", "Compliance Project Assistant + founder")],
  good_to_know=[
   "It calibrates voice from our actual sent mail before drafting — no “I hope this email finds you well”, no em-dashes, no corporate filler.",
   "Stockist reorder emails jump the queue: reorders are the cheapest revenue and never wait.",
   "Complaints and anything reputational get a careful holding draft plus a loud flag — never an improvised answer."]),

 dict(n="16", slug="outbound-sales", business="both",
  title="Outbound Sales — Cold Outreach Drafting",
  tagline="Give it a contact list and a topic; it leaves one tailored first-touch email per contact drafted in Gmail. It never sends.",
  summary="For getting in front of people who've never heard from us — new bottle stores, distributors, hospitality venues, Biz-E prospects — where email is the first touch point. Pass in email addresses (names and context where we have them) plus the hook to lead with, and it writes <strong>one short, tailored draft per contact</strong>: under ~120 words, one hook, one small ask. It checks Gmail history first so a warm contact never gets a cold email, and logs every drafted contact into the pipeline with a follow-up date. Like Sales Watches, it <strong>only drafts — it never sends</strong>.",
  use_when=["A list of new stores or prospects to approach", "A launch worth leading with (e.g. Green Gold)", "Hitting the weekly new-stockist cadence", "Biz-E pilot outreach (when Biz-E resumes)"],
  outputs=[
   ("One Gmail draft per contact", "Tailored, in the founder's voice, segment-correct register (retail vs distributor vs hospitality vs Biz-E), with the likely objection pre-empted."),
   ("Outreach log", "Who was drafted, the hook and subject used, and a follow-up date for each — ready for the CRM Updater to add to the pipeline."),
   ("Gap flags", "Missing names, needed assets (sell sheet, one-pager), and any contact skipped because of prior history.")],
  not_do=[
   ("Sending email — ever. The founder reviews each draft and sends", "founder"),
   ("Follow-ups and replies once a thread exists", "Sales Watches / Sales Manager"),
   ("Setting prices, terms, or claims not in the shared fact files", "founder + Finance Advisor")],
  good_to_know=[
   "First-touch asks are deliberately small — “can I drop a sample in?” beats “become a stockist”.",
   "No fake personalisation: if we don't know anything true about the contact, it says less rather than pretending.",
   "Volume is capped to what the founder can actually follow up — consistency beats a one-off blast."]),
]

OVERVIEW_GROUPS = [
 ("Decide & coordinate", [
  ("Business Operator", "The chief of staff — picks this week's top 3 and routes everything to the right specialist."),
  ("Project Manager", "Lightweight plans for launches and one-off projects: milestones, risks, next actions."),
  ("Calendar Planner", "Places the week's priorities into the hours that actually exist."),
  ("Finance Advisor", "Margins, cashflow, subscription revenue and pricing sanity — with every assumption labelled.")]),
 ("Demand & revenue", [
  ("Marketing Director", "Decides what to say, to whom, where — and writes the brief."),
  ("Content Producer", "Turns briefs into publish-ready posts, newsletters and copy."),
  ("Sales Manager", "Who to follow up, why, and the drafted message — reorders first."),
  ("Sales Watches", "Inbox triage: drafts replies in Gmail, in the founder's voice. Never sends."),
  ("Outbound Sales", "Cold first-touch drafts from a contact list + topic. Never sends."),
  ("CRM Updater", "Keeps the pipeline records true after every interaction.")]),
 ("Whistlebird (craft gin)", [
  ("Distillery Strategy Advisor", "What to make, when to release, where to sell, which awards to chase."),
  ("Compliance Project Assistant", "Licence and label projects: requirements, evidence, deadlines, drafts. Not legal advice.")]),
 ("Biz-E (SaaS for manufacturers)", [
  ("Biz-E Product Manager", "What to build next and why — grounded in real customer pain."),
  ("CTO / Software Architect", "Challenges designs before build; guards security and customer-data isolation."),
  ("Release Manager", "Go/no-go gate, plain-language changelog, and mandatory marketing/sales handoffs."),
  ("Customer Success & Onboarding", "From spreadsheets to a first working process, fast — then health checks.")]),
]

def render_overview():
    accent, tint, _ = ACCENTS["both"]
    css = CSS.format(accent=accent, tint=tint)
    groups = ""
    for gname, rows in OVERVIEW_GROUPS:
        rows_html = "\n".join(
            f'        <tr><td>{name}</td><td>{desc}</td></tr>' for name, desc in rows)
        groups += f"""
  <section class="section">
    <p class="section-label">{gname}</p>
    <table class="group-table">
{rows_html}
    </table>
  </section>
"""
    body = f"""<div class="page">
  <header>
    <p class="eyebrow">Founder Ops · Whistlebird + Biz-E</p>
    <h1>The Skill Library — how we run two businesses on founder time</h1>
    <p class="tagline">16 playbooks Claude can act as — a chief of staff, a sales manager,
    a CTO — each producing concrete, actionable output instead of generic advice.</p>
  </header>

  <div class="summary-box">
    <p class="summary-label">The idea in one box</p>
    <p>Each “skill” is a written playbook that tells Claude how to act as one specific
    role. Ask it to act as the <strong>Sales Manager</strong> and it reads that playbook
    plus the shared business facts, reviews the live pipeline, and hands back drafted
    follow-up emails — not tips about selling. The organising principle:
    <strong>projects create systems, operations run systems.</strong> This library manages
    the changing work (launches, campaigns, pipelines, licences, plans); the Biz-E product
    itself runs the repeatable manufacturing operations.</p>
  </div>
{groups}
  <section class="section">
    <p class="section-label">The weekly rhythm</p>
    <ul class="get-list">
      <li class="get-item"><strong>1 · Business Operator</strong><span>Start of week: pick the top 3 priorities across both businesses and route them.</span></li>
      <li class="get-item"><strong>2 · Sales Manager</strong><span>Draft this week's follow-ups and reorder nudges — the thing that slips first, protected first.</span></li>
      <li class="get-item"><strong>3 · Marketing Director → Content Producer</strong><span>One brief becomes a week of ready-to-post content.</span></li>
      <li class="get-item"><strong>4 · Calendar Planner</strong><span>Everything lands on a specific day that actually exists in the week.</span></li>
    </ul>
  </section>

  <section class="section">
    <p class="section-label">Ground rules every skill follows</p>
    <ul class="know-list">
      <li><span><strong>Never invent facts.</strong> Numbers, dates and claims come from the shared fact files; anything missing is asked for, not guessed.</span></li>
      <li><span><strong>Protect the recipes.</strong> Whistlebird's botanical formulas are never written down, surfaced or inferred.</span></li>
      <li><span><strong>Keep the brands distinct.</strong> Whistlebird (warm, craft, local) and Biz-E (direct, pain-led) never blur — even in the same session.</span></li>
      <li><span><strong>End with actions.</strong> Every output finishes with concrete next steps — each with an owner and a date.</span></li>
    </ul>
  </section>

  <p class="foot">There is one page like this per skill (16 in total). The playbooks
  themselves live in the workspace under <code>skills/&lt;name&gt;/SKILL.md</code>, the
  shared business facts under <code>context/</code>, and the live project state under
  <code>projects/</code>.</p>
</div>"""
    return wrap_document("Founder Ops — The Skill Library", css, body)

os.makedirs(OUT, exist_ok=True)
with open(os.path.join(OUT, "00-overview.html"), "w") as f:
    f.write(render_overview())
for s in SKILLS:
    with open(os.path.join(OUT, f"{s['n']}-{s['slug']}.html"), "w") as f:
        f.write(render(s))
print(f"Wrote {1 + len(SKILLS)} pages to {OUT}")
