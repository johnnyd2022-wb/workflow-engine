# Compliant live-evidence plan

**Status:** in progress — NP3 vertical slice

## Outcome

Compliant is the continuous assurance layer for Core, not a second spreadsheet. Core's
execution and inventory DAG remains the source of truth; an enabled module interprets
that graph through its own control catalogue, records the exact source entities that
support a claim, and turns gaps into an actionable operating queue.

The product must never call an organisation compliant merely because data exists. A
derived item says what Core observed, the source IDs it used, and the control it can
support. Controls that need a human observation, an external document, or a regulator
decision remain explicitly evidence-led.

## NP3 vertical slice

### Evidence graph contract

The NZ Alcohol module projects the following tenant-scoped Core facts in real time:

| NP3 control | Core evidence | Provenance retained | Does not prove |
| --- | --- | --- | --- |
| Traceability, recall and complaints | Completed final-product execution steps traversed backwards through the Core DAG | final inventory IDs, execution-step IDs and execution IDs | recall decision-making or complaint handling |
| Documentation and record keeping | Completed execution records and active Core evidence files | execution-step / file IDs | that every required document exists |
| Suppliers and purchasing | raw-material inventory entries with a named supplier | inventory IDs | supplier approval |
| Receiving food | raw-material entries with supplier, batch and purchase date | inventory IDs | receiving-condition checks |

The NP3 register shows derived items alongside manual records, labels their origin, and
exports the same provenance in CSV. A failed/open/manual overdue item is never hidden by
derived evidence.

### Workflow-time capture

NP3 supports three per-organisation capture modes:

- `off` — no synthetic shelf;
- `recommended` — show the existing Core evidence shelf on every execution step;
- `required` — require an active Core evidence file before a step can complete.

`required` is an explicit administrator decision and is enforced server-side as well as
in the UI. It does not mutate saved process definitions. The evidence still belongs to
Core and is attached to the execution/step, so it is naturally connected to the DAG.

### Pluggable workflow rules

Compliant modules register workflow rules through the platform rule registry. A rule can
contribute a generic prompt and generic Core-owned requirement (for example,
`active_evidence`) with module-owned copy and remediation. Core renders the normalized
prompt and verifies the operational fact, but has no knowledge of the NZ Alcohol module,
NP3, Customs, or any other framework. A future food or chemical module adds a provider in
Compliant's composition root; it does not add industry logic to Core.

## Architecture guardrails

1. **DAG first.** Module evaluators use Core's `DAGTracer` and source entities; they do
   not copy production data into compliance tables.
2. **Evidence has provenance.** Every derived result carries a source kind, stable Core
   IDs, observation time and a human-readable statement. Source IDs are tenant scoped.
3. **Rules are data-driven.** A module supplies a mapping catalogue from control to
   evidence predicate. Core knows only the generic projection/capture interface.
4. **No false green.** Unknown is a gap, not a pass. Derived evidence may support only a
   named control and never asserts certification or regulator acceptance.
5. **Actions live where work happens.** Findings link back to the execution, inventory
   record or the smallest capture action. Modules contribute checks through the existing
   platform registry.
6. **No silent operational breakage.** New capture is recommend-only by default. A
   blocking rule must be visible in Configuration, have a server-side error contract,
   and be tested against direct API completion.

## Delivery sequence

1. Deliver the NP3 DAG projection, provenance-rich register/CSV and configurable capture
   modes. **This change.**
2. Add topic-specific workflow capture templates (temperature, calibration, cleaning,
   allergen controls) selected by process/output classification rather than every step.
3. Add a generic module rule registry and evidence projection cache keyed by Core entity
   events; run module checks from the existing system-findings cache and notify owners.
4. Expand Customs from LAL reconciliation to period-close, stock/dispatch and warehouse
   lineage controls; add external integration adapters only where Core is not authoritative.
5. Add auditor drill-down: one evidence row opens the exact Core DAG subgraph, source
   files, operator, timestamps and corrective-action history.

## Success measures

- A configured NP3 organisation can see which register rows are derived from live Core
  operations and open their source graph without re-entering data.
- A newly completed, traceable Core production run changes NP3 evidence immediately.
- Operators see one clear next action for each gap; administrators can opt into a
  workflow-time evidence constraint without bypassing it through the API.
- Future modules implement a mapping/evaluator, not a parallel data store or workflow.
