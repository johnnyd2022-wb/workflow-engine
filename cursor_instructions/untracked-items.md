Implement a System Check framework for untracked items following the pattern used in expired_materials.py, leveraging corechecks.py and dagtraversal.py.

Requirements:

1. Banner Alerts

Display unresolved untracked items across the system to all relevant operators, similar to expired materials.

Copy existing alert formatting and behavior.

Ensure alerts dynamically update when items are reconciled or added to inventory.

2. Sourcemap Checks

Track all items with no upstream source.

Mark these as “Check needed” in the sourcemap UI, using the same approach as expired materials.

Include reasons for the check, e.g., “Untracked inventory item”, “Reconciliation required”.

Highlight discrepancies between execution inputs and inventory outputs, ensuring operators can see potential negative or unbalanced quantities.

3. Execution Flow Validation

Validate downstream steps that reference these items:

Prevent negative stock or unbalanced quantities from propagating.

Mark dependent steps as blocked or warning if reconciliation is needed.

Maintain consistency with existing DAG traversal logic to determine impact.

4. Implementation Guidelines

Reuse functions from corechecks.py for standard check registration and result reporting.

Use dagtraversal.py to traverse dependencies and update downstream validation.

Ensure all untracked item checks are timestamped, user-stamped, and linked to relevant process/step for auditability.

Include automated update of banners, sourcemap highlights, and downstream execution state when reconciliation occurs.

5. UX Principles

Minimal friction: operators should be able to continue execution while checks exist.

Clear visibility: all unresolved untracked items are visible in banners and sourcemap.

Contextual linking: provide clickable references for mapping items to relevant executions.

Immediate feedback: when an item is reconciled, remove alerts and update inventory in real-time.

Deliver a Python module or extension that integrates with the existing system check framework, is fully testable, and can be called after recording any missing item.