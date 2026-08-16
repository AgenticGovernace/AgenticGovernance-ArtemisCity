# Artemis City Coding Standards

**Version:** 0.2.0

**Status:** Active for new and touched code

**Applies to:** Production Python and TypeScript maintained in this repository

## Purpose

Write the smallest implementation that is safe, clear, testable, and reversible.
Correctness and readable contracts take priority over cleverness, speculative
abstraction, or premature optimization.

These standards are adapted from the earlier JSF-inspired proposal, Python and
TypeScript community practices, and Artemis City's actual governance boundaries.
They describe repository policy; examples or commands in older design documents
remain reference material unless incorporated here.

This is the implementation standard for the Artemis City routing architecture.
No assistant, model, vendor, or desktop application name owns the routing contract.

## Scope

The production gate covers:

- Python under `src/` and the maintained Python API boundary.
- TypeScript under `app/api/` and `app/web/frontend/src/`.
- Tests, configuration, migrations, and scripts used by those components.

The following have separate validation contracts:

- Notebooks and R Markdown are experiment artifacts. They require reproducible
  run manifests but are not automatically production code.
- Generated bundles, build output, caches, and vendored dependencies are not
  hand-edited or linted as source.
- Historical and conflict-copy notebooks cannot become evidence or runtime input
  until a canonical manifest selects them.

Apply these rules incrementally to new and touched code. Do not mass-format or
refactor unrelated files merely to claim compliance.

## Non-negotiable system invariants

1. Authentication, authorization, strict ATP validation, and required provenance
   fail closed. Missing security configuration is an error, not an empty default.
2. A governed `Mode + ActionType` mapping selects the routing domain before any
   learned score is consulted.
3. Explicit policy defines capabilities. Trust, quarantine, and Hebbian weights
   may narrow or rank an authorized candidate set; they cannot add capabilities.
4. Invalid ATP, provider failures, infrastructure errors, and unvalidated outcomes
   are not eligible to update Hebbian weights or trust.
5. SEED is experiment and reproduction metadata only. It is not an authorization,
   domain, trust, or production-routing input.
6. Browser bundles never contain server credentials. Secrets are not logged,
   committed, returned in errors, or copied into generated client assets.
7. Core memory, provenance, validation, and routing rules have one implementation.
   HTTP, MCP, CLI, UI, and storage layers adapt that core rather than duplicate it.
8. MCP stdio transports own stdout. Application diagnostics use stderr or the
   configured logger.
9. A state change that cannot be validated or recorded must not be reported as
   successful.

## Design rules

### Cohesion and coupling

- Each module owns one coherent responsibility.
- Depend on explicit interfaces and typed contracts, not another component's
  internal state.
- Separate parsing, validation, policy, execution, persistence, and presentation
  when they have independent reasons to change.
- Do not introduce an abstraction until there are at least two real consumers or
  a security boundary requires it.

### Complexity and size

- Aim for cyclomatic complexity at or below 10. Complexity above 20 requires a
  documented exception and focused tests.
- Aim for functions near 50 logical lines. A function approaching 200 logical
  lines must be split or justified in review.
- Prefer seven or fewer parameters. Use a typed dataclass or model when a group of
  values forms one domain concept.
- Use early returns where they make control flow clearer; do not fragment a simple
  operation into ceremonial helpers.

### Source-of-truth boundaries

- Configuration values are defined once and passed explicitly.
- Derive environment scope from runtime lookups and deployment configuration, not
  from whichever `.env` file happens to exist.
- Construct patchable paths and stores at call time when tests or environments may
  change them.
- Reverse sync only canonical files named by a manifest. Never sync entire
  experiment, cache, conflict-copy, or generated-output directories.

## Python rules

- Use annotations on public boundaries and meaningful internal functions.
- Prefer concrete built-in generics such as `dict[str, object]` and `list[str]`
  where supported by the project runtime.
- Use Pydantic models or dataclasses for external and cross-component contracts.
  Reject unsupported fields when accepting authority-bearing input.
- Use context managers for files, database transactions, locks, and network
  resources.
- Catch the narrowest useful exception. Broad defensive catches must log enough
  context and must not turn a security or data-integrity failure into success.
- Use `pathlib.Path` and resolved-root containment checks for user-influenced paths.
  Joining a string to a trusted prefix is not, by itself, traversal protection.
- Use `yaml.safe_load`; never use an unsafe YAML loader for untrusted content.
- Initialize values at their narrowest useful scope.
- Name domain thresholds and protocol constants. Ordinary literals that are clear
  in place do not need ceremonial constants.
- Public contracts and non-obvious domain behavior use Google-style docstrings.
  Do not repeat types already expressed by annotations or document trivial code.

## TypeScript rules

- Keep the Python bridge as the only TypeScript-to-Python execution boundary.
- Validate network, process, and persisted input before it reaches domain logic.
- Avoid `any`; when unavoidable at a boundary, narrow it immediately.
- Do not implement parallel authentication, provenance, or routing algorithms in
  TypeScript when Python owns the domain rule.
- Keep server secrets server-side. Frontend configuration contains only public
  values.
- Use explicit result and error shapes for bridge and HTTP contracts.

## Naming, layout, and comments

- Use descriptive names. Abbreviations are limited to established project or
  industry terms.
- Python follows `snake_case`, `PascalCase`, and `UPPER_CASE` conventions.
- Black is authoritative for Python formatting and uses 88 characters.
- Comments explain why a decision or exception exists. They do not narrate an
  obvious statement.
- Module documentation describes responsibility and important side effects. It
  does not contain dependency inventories, version numbers, or license text that
  will drift independently.

## Errors and observability

- Raise specific exceptions at the layer that can describe the failure correctly.
- Translate an exception to an HTTP, MCP, CLI, or UI error only at that boundary.
- Stable error reason codes are preferred for auth, ATP, governance, and
  provenance failures.
- Logs identify the operation and outcome without leaking credentials, raw tokens,
  or unnecessary user content.
- A fallback must be explicit, observable, and policy-authorized. Silent fallback
  is prohibited.

## Testing rules

Every behavior-changing change includes tests proportional to its risk:

- Unit tests cover domain rules and boundary validation.
- Contract tests inspect the client-visible schema and representative errors.
- Security tests assert both the denial and its recorded audit/governance event.
- Routing tests prove unauthorized capabilities cannot be introduced by trust or
  Hebbian scores.
- Learning tests prove invalid or ineligible outcomes cannot change weights.
- Regression tests accompany every repaired production defect.
- Experiment claims identify the run, code version, seed policy, workload,
  parameters, metric definitions, and artifact locations.

Record pre-existing failures separately from regressions. Do not weaken or skip a
gate merely to make a change appear green.

## Documentation and compatibility

- Document public contracts, operational behavior, and breaking changes in the
  same change that implements them.
- Use semantic versioning for released interfaces.
- Preserve behavior during structural extraction. If compatibility cannot be
  preserved, provide an explicit migration and rollback path.
- Keep `AGENTS.md` and `CLAUDE.md` byte-identical as required by the repository.

## Quality gate

The intended non-overlapping gate is:

1. Black for Python formatting.
2. Ruff for Python imports, correctness, style, simplification, and complexity.
3. mypy for maintained Python boundaries.
4. ESLint for maintained TypeScript.
5. pytest for behavior and regression coverage.
6. Bandit, dependency review, and secret scanning for security.

Tool consolidation is incremental. A redundant tool is removed only after the
replacement is configured and its baseline demonstrates equivalent coverage.
`make check` is the operator-facing entry point once the consolidated gate is
complete.

## Deviations

- Generated code and third-party compatibility shims may use a documented local
  exception.
- A safety, contract, or complexity deviation must explain the reason, scope,
  owner, validation, and removal condition in the review record or an ADR.
- Style exceptions should be expressed in the narrowest tool-specific suppression,
  with a short explanation when the reason is not obvious.
