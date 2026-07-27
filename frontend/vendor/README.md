# Frontend vendor assets

Local copies of CDN libraries used by `index.html` so the desktop WebView
chrome works offline (except Tailwind — see below).

| Asset | Source |
|-------|--------|
| `vue.global.prod.js` | vue@3.5.13 |
| `marked.min.js` | marked@15.0.7 |
| `purify.min.js` | dompurify@3.2.5 |
| `highlight.min.js` + `highlight-github.min.css` | highlight.js 11.11.1 |
| `fonts/geist*.woff2` + `geist.css` | geist@1.3.1 |

## Tailwind

`@tailwindcss/browser@4` is a JIT compiler that reads the inline
`<style type="text/tailwindcss">` block at runtime. Fully vendoring it for
offline use is not practical without a build step (compiled CSS export).
Phase 2 keeps the jsDelivr script tag; a later phase can compile Tailwind
ahead of time into a static CSS file.
