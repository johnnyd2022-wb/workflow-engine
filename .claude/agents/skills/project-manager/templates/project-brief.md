# Project Brief — {{project_name}}

_Project brief contract. One file per project under `projects/<business>/`._

```yaml
project_name:
owner:
business: whistlebird | bize
status: proposed | active | blocked | completed
objective:
business_value:
start_date:
target_date:
milestones:
  - name:
    due_date:
    status: not-started | in-progress | done | blocked
    dependencies:
    done_test:
risks:
  - risk:
    impact: low | medium | high
    mitigation:
next_actions:
  - action:
    owner:
    due_date:
```

## Timeline (Gantt)

```mermaid
gantt
    title {{project_name}}
    dateFormat YYYY-MM-DD
    section Milestones
    {{milestone 1}} :m1, {{start}}, {{days}}d
    {{milestone 2}} :after m1, {{days}}d
```

## Weekly update — {{YYYY-MM-DD}}
- **Done:**
- **Blocked:**
- **Next:**

## Handoffs
- → {{skill/tool}}: {{what and why}}
