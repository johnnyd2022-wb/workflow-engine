# Tastings spec critique — round 2

Re-read the updated spec and checked its concrete decisions against the repository surfaces identified in round 1. All six previous gaps are now explicit, reviewable decisions: dedicated tasting ledger and adapters; owner/contract/receipt/source restrictions; Auckland date-only task projection with guarded generic edits; soft planning and atomic reservation; four-decimal mL conservation and replay-safe usage; immutable dated excise basis and late adjustments; bounded input/list/query scope.

No unresolved material contradictions or build blockers remain. The concrete section takes precedence over the earlier shorthand “duty-paid tasting pool”: removal liability evidence must never be represented as actual Customs payment or lodgement, as the new section explicitly requires. Preserve that distinction in models and UI.

Verification must cover the existing lodge path as well as the draft UI: unknown basis cannot be considered nil or complete merely because a client ignores problem rows. This is already required by AC6 and the concrete adapter decisions, not an additional scope request.

No application, tests, scripts or repository docs were edited.

VERDICT: sound
