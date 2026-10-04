# Workspace overview refresh

Founder request, 4 October 2026. Keep existing URLs, access controls and module-owned
status calculations; simplify presentation and navigation across the three workspaces.

- AC1: Production, Compliance and Sales expose at most four primary destinations.
  Secondary pages remain reachable through permission-aware contextual actions;
  their primary parent stays selected. Restricted roles retain their permitted fallback.
- AC2: Production has one navigation row, a plain heading, consistent rectangular
  action buttons and an in-page health card. Add inventory retains manual/file/barcode choices.
- AC3: Health severity changes both wording and colour, with accessible detail access.
  Setup, pending and unavailable states never claim a healthy result.
- AC4: Compliance uses the same simple header/card hierarchy as Sales, preserves
  evidence counts and framework links, and places setup destinations in page actions.
- AC5: At 1440 and 390 px, main overviews have readable spacing and no horizontal
  page overflow. Legacy deep links and boosted navigation remain functional.

Screenshots are evidence for manual visual inspection, not fragile pixel-diff tests.
Existing auth, form validation and tenant-isolation suites cover unchanged controls.
