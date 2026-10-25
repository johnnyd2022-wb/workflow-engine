# PAGE DESIGN — task-settings — 2026-10-25
plan: docs/task-settings-redesign-plan.md
research: shared with the settings pages (Primer, Polaris, GitLab study, GOV.UK, Linear, Stripe, Katana, Breww)
directions: 3 (Cards, Side by side, Read first); chosen: Style 1 (Cards)
passes: 2   defects fixed: 1   bugs fixed: settings loaded twice (double x-init); a failed load left defaults that could be saved over the real settings; no confirmation on save
screenshots: ~/.cache/workflow-engine-ui-shots/config-survey/00-before, tasks/01 .. 02
tests: 6 browser cases passed after the approved layout was applied
follow-ups: Sales tasks archive vs Production Task settings
verdict: patched — founder-approved layout applied
