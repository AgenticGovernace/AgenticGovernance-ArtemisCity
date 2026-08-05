# Artemis City Dashboard Routing and Security Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the React dashboard use React Router as the application navigation contract so users can move between dashboard areas, task records, and reports through safe, refreshable URLs while preserving the existing FastAPI authorization and filesystem containment boundaries.

**Architecture:** Keep the dashboard in React Router declarative mode with one `BrowserRouter`, a shared layout route, explicit page routes, parameterized detail routes, and a catch-all not-found route. Route destinations and route segments live in one small module; pages use API identifiers returned by the server and never turn browser route parameters into filesystem paths. The FastAPI dashboard remains the source of truth for task execution and report reads.

**Tech Stack:** React 18, React Router 7 declarative APIs (`BrowserRouter`, `Routes`, `Route`, `Link`, `NavLink`, `useParams`, `useSearchParams`), Chakra UI, Vite, TypeScript, FastAPI, and the existing authenticated `/api/*` client.

## Global Constraints

- Keep `app/web/frontend` on React Router declarative mode until the project deliberately migrates to React 19-compatible data/framework mode.
- Keep the frontend-to-backend boundary on `app/web/frontend/src/api.ts`; do not read the Obsidian vault or reimplement task routing in browser code.
- Treat every route parameter as untrusted display/query input; task execution must use the server-provided `relative_path`, and report reads must continue through the authenticated API.
- Preserve the backend's report containment checks and existing `X-API-Key` behavior.
- Use `apply_patch` for source edits, preserve unrelated working-tree changes, and do not commit or push unless separately requested.
- Verification must include the frontend TypeScript/build checks, focused backend security tests, and a final diff review.

## Baseline Findings and Decisions

- The dashboard already has a single `BrowserRouter` and a shared `Layout`/`Outlet`, but only collection routes exist; tasks and reports cannot be opened as refreshable detail URLs.
- Sidebar destinations are duplicated as string literals in `Layout.tsx`, while page links do not share a route contract. This makes navigation drift likely as the dashboard grows.
- The Tasks page executes a task from its API-returned `relative_path`, which is the correct security boundary. Phase 1 retains that behavior and adds a task detail route that resolves by exact `task_id` from `GET /api/tasks`.
- The Reports page currently uses a local full-screen modal. Phase 1 changes this to a route-backed report view so browser back/forward, reloads, and shareable links work. The existing backend path containment check remains authoritative.
- The current dependency upgrade leaves the dashboard in React 18 declarative mode. The newer React Router RSC advisory is tracked as a compatibility-gated Phase 5 item because the dashboard does not use RSC, SSR, `createStaticRouter`, or framework mode.

---

## Phase 1 — Secure Navigation and Task Interaction (complete)

**Outcome:** Users can navigate from collections to task/report details, use browser history and refresh, filter tasks through a URL query, and safely return to known dashboard pages. Invalid route parameters fail closed in the UI and never bypass the authenticated API.

### Task 1: Establish the route contract

**Files:**

- Create: `app/web/frontend/src/router/paths.ts`
- Create: `app/web/frontend/src/router/paths.test.ts`
- Modify: `app/web/frontend/package.json`
- Modify: `app/web/frontend/src/App.tsx`
- Modify: `app/web/frontend/src/components/Layout.tsx`

**Interfaces:**

- `routePaths.dashboard`, `.tasks`, `.reports`, `.agents`, `.database`, and `.executor` are stable collection destinations.
- `routePaths.task(taskId: string)` and `routePaths.report(filename: string)` return encoded detail destinations.
- `routeSegments` contains the route declaration segments used by `App.tsx`.
- `isSafeReportFilename(filename: string)` accepts only the generated report filename shape: a Unicode letter/number or hyphen first character, safe filename characters, a `.md` suffix, and a maximum of 255 characters.

- [x] Add the shared path and segment constants without changing the current public URLs.
- [x] Replace sidebar destination literals with `routePaths` values.
- [x] Add explicit routes for `/tasks/:taskId` and `/reports/:filename`.
- [x] Add a lazy-loaded `NotFound` route for unmatched paths.
- [x] Keep one top-level `BrowserRouter`; do not nest routers inside pages.

### Task 2: Make task movement and execution route-aware

**Files:**

- Create: `app/web/frontend/src/pages/TaskDetails.tsx`
- Modify: `app/web/frontend/src/pages/Tasks.tsx`
- Modify: `app/web/frontend/src/api.ts`
- Modify: `app/api/main.py`
- Test: `src/tests/test_dashboard_api.py`

**Interfaces:**

- `TaskDetails` reads `taskId` with `useParams` and calls authenticated `fetchTask(taskId)`, which resolves an exact task ID on the server across all task statuses.
- `GET /api/tasks/{task_id}` compares the identifier with parsed task metadata and never turns it into a vault path; `GET /api/tasks` remains the pending execution queue.
- `TaskDetails` calls `executePendingTask(task.relative_path)` only for a task object returned by the API; it never constructs a vault path from `taskId`.
- `Tasks` writes the selected status filter to `?status=` using `useSearchParams` and links each row to `routePaths.task(task.task_id)`.

- [x] Add a status filter whose accepted values are `all`, `pending`, `in progress`, `completed`, and `failed`; unknown query values fall back to `all`.
- [x] Add “View” navigation for each task and preserve the existing pending-only Execute action.
- [x] Add an exact-ID task detail API so a task URL remains valid after execution moves it out of the pending queue.
- [x] After successful task creation, navigate to the returned `task_id` detail route when present; otherwise refresh the collection.
- [x] Add a task detail page with title, status, agent, routing metadata, context, keywords, target, subtasks, a pending-only Execute button, and a return link.
- [x] Render loading, not-found, API-failure, and execution-failure states without exposing exception details or route-derived filesystem paths.

### Task 3: Make report movement and Markdown rendering safe

**Files:**

- Create: `app/web/frontend/src/pages/ReportDetails.tsx`
- Create: `app/web/frontend/src/components/ReportMarkdown.tsx`
- Create: `app/web/frontend/src/pages/NotFound.tsx`
- Modify: `app/web/frontend/src/pages/Reports.tsx`

**Interfaces:**

- `ReportDetails` validates `filename` with `isSafeReportFilename` before calling `fetchReportContent`.
- `ReportMarkdown` keeps raw HTML disabled (the `react-markdown` default) and allows only relative/hash links plus `http`, `https`, `mailto`, and `tel` URLs. HTTP(S) links open in a new tab with `rel="noreferrer"`.
- `Reports` links only safe API-listed filenames to `routePaths.report`; invalid records are displayed as unavailable rather than turned into navigable URLs.

- [x] Replace the local report modal with links to `/reports/:filename`.
- [x] Add a route-backed report page with loading, invalid-reference, missing-report, and API-failure states.
- [x] Move the existing dark-theme Markdown styling into `ReportMarkdown` so collection and detail pages do not duplicate rendering policy.
- [x] Keep report content fetched through `fetchReportContent`, which retains URL encoding, API-key injection, and the backend containment check.
- [x] Add a not-found page with a safe link to the dashboard root.

### Task 4: Verify Phase 1 and record evidence

**Files:**

- Modify: `plan.md`

- [x] Run `npm --prefix app/web/frontend run typecheck`.
- [x] Run `npm --prefix app/web/frontend run build`.
- [x] Run `npm --prefix app/web/frontend run test:routes`.
- [x] Run the focused backend tests covering dashboard task/report behavior and path traversal.
- [x] Run `git diff --check` and inspect the final diff for route-param-to-filesystem mistakes.
- [x] Mark the Phase 1 checkboxes complete only after all required commands return exit code 0.

### Phase 1 completion record

- `npm --prefix app/web/frontend run typecheck` — exit 0.
- `npm --prefix app/web/frontend run build` — exit 0; Vite transformed 1,213 modules and emitted route-specific chunks for Tasks, TaskDetails, Reports, ReportDetails, and NotFound.
- `npm --prefix app/web/frontend run test:routes` — exit 0; encoded destination and unsafe report filename assertions passed.
- `uv run pytest -q src/tests/test_dashboard_api.py src/tests/test_api_bridge.py src/tests/test_obsidian_manager.py -k 'sanitize or report or traversal or path or stack or error or bridge or note'` — `70 passed, 16 deselected`.
- `git diff --check` — exit 0.
- `npm --prefix app/web/frontend run lint` remains a pre-existing configuration blocker: `eslint-plugin-react-hooks` does not expose `configs.flat.recommended` at the installed version, so ESLint fails while loading `eslint.config.js` before linting source files. This is tracked outside Phase 1 and is not represented as a passing lint result.

**Phase 1 acceptance criteria:**

1. `/`, `/tasks`, `/tasks/:taskId`, `/reports`, `/reports/:filename`, `/agents`, `/database`, and `/executor` have explicit route behavior.
2. Sidebar links and page links use the shared route contract.
3. Browser back/forward and direct reloads remain meaningful at collection and detail URLs, subject to the deployment serving the SPA entry point.
4. Task execution uses an API-returned `relative_path`; no task route parameter is passed to an execution endpoint.
5. Report route parameters are validated in the client and still read only through the existing authenticated, containment-checked backend endpoint.
6. Markdown cannot create an unsafe `javascript:`, `data:`, or protocol-relative link through the report viewer.
7. TypeScript compilation, Vite production build, focused backend tests, and whitespace checks pass.

---

## Phase 2 — Route-Aware Data and Error Boundaries

**Outcome:** Every page has consistent loading, retry, empty, and authorization states, and route transitions do not leave stale data visible.

**Files:**

- Modify: `app/web/frontend/src/api.ts`
- Create: `app/web/frontend/src/components/RouteStatus.tsx`
- Create: `app/web/frontend/src/components/RouteErrorBoundary.tsx`
- Modify: `app/web/frontend/src/App.tsx`
- Modify: `app/web/frontend/src/pages/Tasks.tsx`
- Modify: `app/web/frontend/src/pages/Reports.tsx`
- Modify: `app/web/frontend/src/pages/TaskDetails.tsx`
- Modify: `app/web/frontend/src/pages/ReportDetails.tsx`

**Implementation steps:**

- Return typed API envelopes for task, report, and error responses while preserving the current endpoint shapes.
- Add abort-aware fetch calls so an unmounted detail page cannot update state after a route transition.
- Normalize 401, 403, 404, 409, and 5xx responses into user-safe messages while retaining server-side diagnostic logging.
- Add route-level error boundaries around page content so one page failure does not blank the application shell.
- Add tests for stale-request cancellation, unauthorized responses, and safe generic error copy.

**Gate:** TypeScript build, API tests, and a Playwright smoke test for direct navigation to task and report URLs.

---

## Phase 3 — Governed Task Workflow Navigation

**Outcome:** Users can understand and follow a task from creation through routing, execution, report persistence, and provenance without leaving the dashboard.

**Files:**

- Modify: `app/web/frontend/src/pages/TaskDetails.tsx`
- Create: `app/web/frontend/src/pages/TaskActivity.tsx`
- Modify: `app/web/frontend/src/pages/Reports.tsx`
- Modify: `app/web/frontend/src/api.ts`
- Modify: `app/api/main.py` only when a read-only task/provenance endpoint is needed
- Add focused coverage in `src/tests/test_dashboard_api.py` and frontend route tests

**Implementation steps:**

- Add a read-only task activity view keyed by server-issued task ID and provenance ID.
- Link a completed task to its report only from server-returned report metadata; do not guess report paths in the browser.
- Display routing decision, selected agent, capability, provider, outcome class, and provenance identifiers using the existing response contract.
- Keep execution actions permissioned by the existing API key and task status; disable duplicate execution while a request is in flight.
- Add API tests that prove unknown task IDs and unauthorized activity requests do not expose vault data.

**Gate:** Live dashboard API contract tests, focused provenance tests, and a browser workflow from task creation to report link.

---

## Phase 4 — Deployment and Navigation Hardening

**Outcome:** Production refreshes and observability behave consistently for every supported client route.

**Files:**

- Modify: the production static-server/container configuration that serves `app/web/frontend/dist`
- Modify: `.github/workflows/*` route/build checks as applicable
- Create: frontend route smoke tests under the repository's established browser-test location
- Update: `README.md` with the SPA fallback requirement and supported route table

**Implementation steps:**

- Configure the production server to serve `index.html` for known client-side routes while preserving `/api/*` and `/health` routing.
- Add a CI check that builds the frontend and probes each collection/detail route through the deployed static server.
- Add browser assertions for navigation, keyboard focus, mobile drawer closing, back/forward, and direct reload.
- Add CSP and link-policy checks appropriate to the deployment layer without placing secrets in the client bundle.

**Gate:** CI build, deployment smoke test, and security review of static-server fallback and headers.

---

## Phase 5 — React Router Compatibility and Dependency Follow-up

**Outcome:** The project can make a deliberate, tested decision about the remaining React Router advisory and future data/framework mode.

**Files:**

- Modify: `app/web/frontend/package.json`
- Modify: `app/web/frontend/package-lock.json`
- Modify: `app/web/frontend/src/App.tsx` and route modules only if the migration is approved
- Update: this plan with the selected compatibility decision

**Implementation steps:**

- Re-check the current React Router advisories against the actual installed package versions and the code's use of declarative mode.
- Do not force React Router 8 or React 19 into this React 18 dashboard as a blind dependency change.
- If the project elects to migrate, first upgrade React and React DOM together, then run the full frontend build and browser suite before changing router mode.
- Record the accepted risk or migration decision with package versions, affected modes, and verification evidence.

**Gate:** Dependency audit, compatibility review, full frontend/browser verification, and explicit maintainer approval.

---

## Final Verification Matrix

| Claim | Required evidence |
|---|---|
| Route contract is implemented | `app.tsx`, `router/paths.ts`, and final diff show explicit collection/detail/catch-all routes |
| Task execution remains safe | Task detail calls `executePendingTask` with API-returned `relative_path`; backend path/security tests pass |
| Report reads remain safe | Client filename validation plus existing backend traversal/symlink tests pass |
| User movement works | TypeScript build plus browser smoke coverage for links, back/forward, refresh, and mobile navigation |
| Phase 1 is complete | All Phase 1 checkboxes are checked and the verification commands have fresh exit-code-0 output |
