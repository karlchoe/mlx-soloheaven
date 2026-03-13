# WEB KNOWLEDGE

## OVERVIEW
Static browser UI shipped inside the Python package: chat page plus admin dashboard, served directly by FastAPI without a frontend build step.

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| Main chat shell | `index.html` | Entry page for the built-in UI |
| Admin dashboard shell | `admin.html` | Log viewer, cache/db overview, reset controls |
| Shared styling | `style.css` | Largest frontend asset; responsive styling and theme rules |
| Client behavior | `app.js` | Session/chat UI logic and admin interactions |

## CONVENTIONS
- Keep assets framework-free and directly serveable from `StaticFiles`.
- Changes here should assume no bundler, transpiler, or asset pipeline.
- The UI is operational, not decorative; cache/model/admin visibility matters more than polish alone.

## ANTI-PATTERNS
- Do not introduce a Node-based build step for small changes.
- Do not assume an API gateway layer; browser code talks to the FastAPI routes directly.
- Do not move files without updating the static mounting assumptions in `server.py`.

## NOTES
- `admin.html` and `style.css` are both large enough that targeted edits are safer than broad rewrites.
- There are no frontend tests or linting rules in this repo.
- Admin screens depend on live backend routes and SSE log streaming, so UI changes often need route-level verification.
- Because there is no asset pipeline, every browser-facing change should remain plain HTML/CSS/JS that runs as-is.
- `app.js` is the behavior hub; prefer keeping logic there rather than spreading inline scripts across HTML files.
- If you rename frontend endpoints, audit both `app.js` and admin page behaviors together.
