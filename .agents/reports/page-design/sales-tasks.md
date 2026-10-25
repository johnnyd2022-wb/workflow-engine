# PAGE DESIGN — sales-tasks — 2026-10-24
plan: docs/sales-tasks-redesign-plan.md
research: 3 comparable products (HubSpot tasks, Pipedrive activities, Trello-style board), 2 craft references (Linear, Todoist Upcoming), 1 pattern source (kanban UX write-ups; NN/g not found)
directions: 3 (Board, Due list, Week); chosen: Board, List and Week as permanent user-selectable views
passes: 5   defects fixed: 9   bugs fixed: due dates on the UTC day (a day early in NZ); everything loaded twice (x-init plus Alpine's own init), which also duplicated the custom lane
screenshots: ~/.cache/workflow-engine-ui-shots/sales-tasks/00-before, 01–05
tests: 39 Sales Tasks and Sales design browser cases passed; all views retained as product features
follow-ups: the same double x-init on Configuration, Analytics, Batch matching, Customer detail and Excise
verdict: patched — founder-approved layout applied
