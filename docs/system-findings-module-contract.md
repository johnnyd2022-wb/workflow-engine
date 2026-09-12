# System-finding module contract

## Boundary

Product modules own their compliance or operational alert content. Core owns transport,
safe rendering, dismissal, snoozing, and generic navigation only. Do not add a module
or product check-ID branch to either Core system-findings frontend script.

The only exception is a Core-owned check with a genuinely Core-specific interaction, such
as reconciliation. A new module must use the contract below instead.

## Module payload

A module check returns a normal `CheckResult`. To make it usable in Core's System Findings
banner and Notifications, it may put these JSON-safe keys in `CheckResult.data`:

```python
{
    "system_finding": {
        "category": "Human-readable module category",
        "action": {"href": "/internal/path", "label": "Open workspace"},
        "details": [
            {
                "title": "What needs action",
                "description": "Why it matters and what to do next.",
                "href": "/internal/path/to/action",  # optional
                "action_label": "Open action",         # optional
            },
        ],
    },
    "system_alerts": [
        {
            "id": "stable-module-alert-key",
            "title": "One clear action",
            "description": "The useful context for an operator.",
            "due_date": "2026-09-12",                  # optional ISO date/datetime
            "href": "/internal/path/to/action",        # optional
            "action_label": "Open action",             # optional
        },
    ],
    "workspace_summary": {
        "workspace": "compliant",
        "module_name": "NP3",
        "href": "/compliant/nz-alcohol/food-safety",
        "action_label": "Open NP3",
        "score": 11,
        "current_controls": 4,
        "total_controls": 38,
        "evidence_ready": 4,
        "needs_attention": 34,
        "overdue": 0,
    },
}
```

`system_finding` controls the one summary row in the Core banner. `system_alerts` creates
one notification card per alert and supplies the banner detail list. Emit both keys for
actionable work so the same signal reaches operators in both Core surfaces.

`workspace_summary` is optional. Use it when a module has a compact, operator-facing
health snapshot that belongs on the shared Dashboard workspace card. The module owns its
numbers and labels; Core groups and renders summaries by the declared `workspace` only.

## Rules

- `id` is required, stable for the underlying action, and unique within the module check.
  It is the dismissal/snooze key, so never use an array index or a timestamp.
- All strings are plain text. Never provide HTML.
- `href` must be an internal, root-relative path. Core rejects protocol-relative or
  external destinations before rendering.
- Keep the summary focused. Put module-specific evidence, people, control IDs, and next
  steps in `details` and `system_alerts`, not in Core code.
- `workspace_summary.workspace` identifies the destination card (for example,
  `compliant`). Never make Core branch on the emitting module check ID.
- Preserve the module's original domain data separately when its own workspace needs it;
  the system-finding contract is a presentation boundary, not a replacement data model.
- Add a contract test proving the module emits the payload, and a static guard that Core
  does not mention the module check ID.

## Implementation locations

- Contract definition: `app/core/backend/corechecks.py` (`CheckResult`).
- Generic banner renderer: `app/core/frontend/js/system-findings-banner.js`.
- Generic notifications renderer: `app/core/frontend/js/system-findings-notifications.js`.
- Example module: `app/features/compliant/modules/nz_alcohol/module.py`.
