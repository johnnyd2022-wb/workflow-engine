# Self-hosted fonts

| File | Family | Licence | Source |
|---|---|---|---|
| `roboto-latin*.woff2` | Roboto (variable, 400–700) | SIL Open Font License 1.1 | https://fonts.google.com/specimen/Roboto |
| `inter-latin*.woff2` | Inter (variable, 400–800) | SIL Open Font License 1.1 | https://fonts.google.com/specimen/Inter |
| `momo-trust-display-latin*.woff2` | Momo Trust Display | SIL Open Font License 1.1 | https://fonts.google.com/specimen/Momo+Trust+Display |

Only the `latin` and `latin-ext` subsets are kept (latin-ext carries the macrons te reo Māori
needs). `../css/fonts.css` holds the `@font-face` rules with Google's unicode ranges.

To refresh: request
`https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;600;700&family=Inter:wght@400;500;600;700;800&family=Momo+Trust+Display&display=swap`
with a current Chrome user agent, download the latin and latin-ext `woff2` URLs, and keep the
file names above.
