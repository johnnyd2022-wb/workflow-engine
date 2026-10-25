# PAGE DESIGN — compliance-settings — 2026-10-25
plan: docs/compliance-settings-redesign-plan.md
research: 2 comparable products (Katana, Breww), 2 craft references (Linear members, Stripe team), 4 pattern sources (Primer saving, Polaris save bar, GitLab settings study, GOV.UK summary list)
directions: 3 (Cards, Side by side, Read first); chosen: Style 1 (Cards)
passes: 3   defects fixed: 7   bugs fixed: a failed load left the form on screen with Compliance unticked, so a Save switched it off; the Licensing tab didn't follow a licence change until reload
screenshots: ~/.cache/workflow-engine-ui-shots/config-survey/00-before, compliance/01 .. compliance/03
tests: 7 browser cases passed after the approved layout was applied
follow-ups: server-side merge of profile settings
verdict: patched — founder-approved layout applied
