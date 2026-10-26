# PAGE DESIGN — customs-transfers — 2026-10-26
plan: docs/cca-transfers-plan.md
research: NZ Customs op. policy (paras 7, 11, 15, 16), EMCS/HMRC BEER7040, TTB 27 CFR 19.405/25.292, GOV.UK task list, Vanta/Drata controls; Ekos/DistillX5/Orchestrated help not reachable
directions: 3 (Register, To do, By destination); chosen: Style 1 (Register)
passes: 8   defects fixed: 6
bugs fixed: departure date compared in UTC, not NZ time
screenshots: ~/.cache/workflow-engine-ui-shots/transfers/01-08
tests: 8 unit + 6 e2e added
follow-ups: contract-order dispatch (GL-P08 part 2), a register export
verdict: patched
