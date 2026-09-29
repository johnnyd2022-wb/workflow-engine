# How Compliant plugs into Core

Plan item 2.4a. Every part of NZ Alcohol (NP1, NP2, NP3, Customs, liquor licensing) and
any later industry pack is built to this contract. Core owns the operational facts
(workflows, steps, executions, stock, evidence files). A Compliant module owns the rules
and the words. Core never names an industry, programme or regulator.

The Semgrep rules `core-no-industry-specific-compliance-python` and
`core-no-industry-specific-compliance-javascript` enforce the boundary. Code under
`app/core/` may not mention NP3, NZ Alcohol, or import `app.features.compliant.modules.*`.
Core only imports the platform seams in `app/features/compliant/platform/`.

## The composition root

A module is installed by listing it in the platform seams. Nothing else changes in Core.

| Seam | File | What the module supplies |
| --- | --- | --- |
| Checks | `platform/registry.py` → `register_enabled_module_checks` | `register_checks(runner)`: each check is `(org_id, session) -> CheckResult` |
| Workflow rules | `platform/workflow_rules.py` → `_providers()` | an object with `workflow_rules(session, org_id, step_id=None)` |
| Stock measures | `platform/stock_measures.py` → `_providers()` (with !410) | an object with `measure`, `flows`, `declared`, `labels`, … |

## Workflow rules: fields and constraints on steps

A provider returns `WorkflowRule`s:

```python
WorkflowRule(
    rule_id="nz-alcohol.abv-required",          # stable, namespaced by module
    prompt={"type": "number", "label": "ABV (%)", "required": True, "min": 0, "max": 100, "help": "..."},
    constraints=(WorkflowConstraint(requirement="prompt_value", prompt_label="ABV (%)",
                                    minimum=Decimal("0"), maximum=Decimal("100"),
                                    code="compliance_requirement_not_met", message="...", action="..."),),
)
```

- **Prompts** are shown by Core on the step, from `workflow_context()`. Core renders the
  generic prompt types (`text`, `number`, `date`, `select`, `evidence`) and nothing
  module-specific. Only `rule_id` and `prompt` leave the server; constraints stay
  internal.
- **Constraints** are what Core enforces when a step is completed
  (`completion_constraints()`, called by the step-completion route). Core knows how to
  check each `requirement` against a fact it owns:
  - `prompt_value`: the submitted value for `prompt_label` is present and within
    `minimum`..`maximum`.
  - `active_evidence`: the step has an active evidence file on this execution.

  A failed constraint returns 409 with the module's `code`, `message` and `action`.
  Adding a new requirement kind means teaching Core a new generic fact. It never means
  adding module logic to Core.
- **Step scoping:** `workflow_rules()` receives the step *definition* id when Core knows
  it. With `step_id=None` it must return only rules that apply to every step. A rule for
  particular steps (for example ABV on a final product) is returned only when that step
  is asked about.
- **How steps are matched** (the NZ Alcohol pattern; reuse it):
  - A workflow's *final step* is the one with the highest `position`, then the highest
    `step_number`.
  - Products are matched on the final step's **output names**: `exact` or `contains`,
    case-insensitive, and `exact` wins over `contains`. This is the same rule shape the
    CRM uses to map Xero items, so one broad phrase (e.g. contains "final product") also
    covers workflows created later.
  - Producers keep their workflows. A module adds fields to matching steps and never
    rewrites a workflow.

## Checks: alerts, findings and the dashboard

A check returns `CheckResult(check_id, flagged, message, data)`. Core reads these keys of
`data` generically:

| Key | Shape | Where it shows |
| --- | --- | --- |
| `system_alerts` | list of `{id, title, description, due_date?, href?, action_label?}`; `id` is stable, so an alert isn't repeated | notifications / alert list |
| `system_finding` | `{category, action: {href, label}, details: [alert…]}` | system findings |
| `workspace_summary` | `{workspace, module_name, href, action_label, score, current_controls, total_controls, evidence_ready, needs_attention, overdue, milestone?}` | the dashboard's module card |
| `workspace_summary.milestone` | `{label, date, overdue, detail?}` (e.g. next verification) | one line under the score (!412) |

Anything else in `data` is module-private.

Conventions:
- Checks are cheap and live (uncached), so gate on `profile.enabled` first.
- Alerts appear when there's still time to act: renewals from 60 days before the
  deadline, reviews from 30, actions from 7. Overdue items say so in the description.
- `href` is always a same-origin path. Core drops anything else.

## Module pages

- Pages live under `/compliant/<module>/…` in the module's own blueprint, registered in
  `compliant_bp.py` so the Compliant subscription gate applies.
- Every route has a rule in `app/core/security/access_policy.py`: viewing needs
  `compliance.view`, recording needs `compliance.record`, and configuring registers or
  settings needs `compliance.manage`. `test_every_route_has_an_explicit_rule` fails
  without one.
- Settings a module keeps on the compliance profile, but which aren't part of the main
  configuration form, go in `_SUBFEATURE_SETTINGS` so a configuration save keeps them.
- Evidence uses the shared `ComplianceRecord` (framework slug + control id) and the
  shared training/competency register, so audit packs and counts stay consistent.

## Building a new part: the checklist

1. Put the rules (catalogue, frequencies, due dates) in `modules/<module>/` with the
   source cited in the module docstring. Test every rule, not just the happy path.
2. Add fields to steps through a `WorkflowRuleProvider`. Don't touch Core.
3. Raise reminders through a check's `system_alerts`, and add a `milestone` if there's
   one date that should always be on screen.
4. Add the page and routes in the module's blueprint, with access-policy rules.
5. Switching the part on must not change anyone's workflow, only add fields to steps.
