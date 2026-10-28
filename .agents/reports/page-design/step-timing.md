# PAGE DESIGN — step timing — 2026-10-28

plan: docs/step-timing-redesign-plan.md
research: 3 comparable products, 2 craft references, 1 pattern source
directions: 3 (Fields, Sentence, Timeline); chosen: Timeline (Style 3, founder choice)
passes: 5; defects fixed: 2 (planner prefill; invalid timing no longer shows a zero-duration bar)
screenshots: /tmp/step-timing-shots-01, /tmp/step-timing-shots-02, /tmp/step-timing-shots-03, /tmp/step-timing-final-shots, /tmp/step-timing-final-shots-02
tests: process-design and planning tests for timing and expiry; workflow-editor browser coverage of the chosen layout at phone and desktop widths
follow-ups: later planning stages cover capacity and production calendars
verdict: patched

The first two concept passes showed only the top of the timing section because the wizard scroll position was too high. The third concept pass showed the control at desktop and phone widths and in dark mode. After the founder chose Style 3, the other layouts and switch were removed. The first single-style pass revealed that invalid timing still showed a zero-duration graphic; the second fixed this. Its empty, entered, invalid, phone, dark, and return-visit screenshots were all read and showed no clipping, horizontal overflow, or console errors.
