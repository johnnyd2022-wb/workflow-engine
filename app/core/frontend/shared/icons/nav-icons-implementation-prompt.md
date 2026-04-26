# Nav Icons Implementation Prompt

Use the following prompt when asking Claude to implement the nav icons:

---

Implement the sidebar/bottom navigation for biz-e using the four attached SVG icons (icon-dashboard.svg, icon-core.svg, icon-integrations.svg, icon-settings.svg).

**Colour system:**
- Inactive state: `#94A3B8` (cool slate)
- Active state: `#2DD4BF` (bright teal)
- Active background pill: `#2DD4BF` at 10% opacity (`rgba(45, 212, 191, 0.1)`)
- Nav label inactive: `#94A3B8` at 60% opacity
- Nav label active: `#2DD4BF` at full opacity, font-weight 500

**The SVGs use `currentColor`** so you can control the icon colour entirely via CSS `color` property. Set `color: #94A3B8` on the inactive nav item and `color: #2DD4BF` on the active one — no need to touch the SVG internals.

**Layout:**
- Desktop/tablet: vertical sidebar on the left, icons + labels stacked
- Mobile: fixed bottom tab bar, icons + labels horizontal
- Icon render size: 24px × 24px on mobile tab bar, 28px × 28px in sidebar
- Each nav item should have sufficient tap target (min 44×44px)

**Nav items (in order):**
1. Dashboard — icon-dashboard.svg
2. Core — icon-core.svg
3. Integrations — icon-integrations.svg
4. Settings — icon-settings.svg

**Active state behaviour:**
- Highlight the active nav item with `color: #2DD4BF` and a subtle `background: rgba(45, 212, 191, 0.1)` pill/row behind it
- No border or underline needed — the colour change alone carries the active state
- Transition: `color 150ms ease, background 150ms ease`

**Background colours the nav sits on:**
- Dark blue sidebar: `#0F1F3D`
- Charcoal variant: `#2D2D2D`
- The icon colours (`#94A3B8` and `#2DD4BF`) are tested and confirmed to work on both.

**Warning/error colours are separate** — do not use `#2DD4BF` for success states. Reserve a distinct colour (e.g. green) for success and red/amber for warnings so teal remains exclusively a navigation accent.
