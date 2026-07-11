# Product Launch Plan — {{product_name}}

_For a new Whistlebird product (e.g. Solstice). Pairs with Marketing Director, Content
Producer, Sales Manager, and Compliance Project Assistant. **Handoff rule:** once
repeatable commercial production begins, execution moves to **Biz-E**._

```yaml
project_name: "Launch {{product_name}}"
owner:
business: whistlebird
status: proposed | active | blocked | completed
objective:
target_launch_date:
positioning: "{{e.g. juniper-forward, savory; blue+yellow label}}"
```

## Milestones (typical launch spine)
| # | Milestone | Owner | Due | Status | Depends on |
|---|---|---|---|---|---|
| 1 | Recipe lock (private) | | | | |
| 2 | Stability / sensory testing | | | | 1 |
| 3 | Costing & pricing | | | | 1 |
| 4 | Label design | | | | positioning |
| 5 | Label / regulatory approval | | | | 4 |
| 6 | Bottle & closure decisions | | | | |
| 7 | Photography | | | | 4,6 |
| 8 | Website copy & product page | | | | 3,7 |
| 9 | Launch content pack | | | | 7,8 |
| 10 | Distributor messaging | | | | 3,8 |
| 11 | Retailer outreach | | | | 9,10 |
| 12 | Awards calendar / submissions | | | | 2 |

## Timeline (Gantt)
```mermaid
gantt
    title Launch {{product_name}}
    dateFormat YYYY-MM-DD
    section Product
    Recipe lock            :a1, {{start}}, 7d
    Stability testing      :after a1, 21d
    Costing & pricing      :after a1, 5d
    section Brand
    Label design           :b1, after a1, 14d
    Label approval         :after b1, 21d
    Photography            :after b1, 7d
    section Go-to-market
    Website & content      :c1, after b1, 10d
    Distributor & retailer :after c1, 14d
```

## Risks
- {{recipe/stability risk — e.g. pink→orange under UV}} — _impact · mitigation_
- {{supplier lead-time on bottles/labels}} — _impact · mitigation_
- {{label approval timeline}} — _impact · mitigation_

## Next actions
- [ ] {{action}} — _owner · due_

## Handoffs
- → **Marketing Director:** launch marketing brief once positioning + date are set.
- → **Sales Manager:** distributor/retailer outreach + reorder tracking.
- → **Compliance Project Assistant:** label approval / licensing tasks.
- → **Biz-E:** production, inventory, and compliance records once production is repeatable.
