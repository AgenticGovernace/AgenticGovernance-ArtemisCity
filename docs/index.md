# Artemis City

Artemis City is a governed multi-agent orchestration platform with
trust-aware routing, a persistent memory bus, ATP message handling, and both
Python and web-facing runtime layers.

## Start here

- [Install the project](INSTALL.md) using the root Makefile and locked
  dependency sets.
- Read the [architecture](ARCHITECTURE.md) for the runtime design and system
  boundaries.
- Use the [repository layer map](REPOSITORY_LAYERS.md) to find each maintained
  source of truth, entry point, state store, and test surface.
- Use the [API reference](API_REFERENCE.md) for ATP messages and HTTP
  endpoints.
- Browse the [Python contract reference](PYTHON_API.md) for rendered authority
  and ATP validation docstrings.
- Follow the [test plan](TEST_PLAN.md) before promoting a change.
- Review the [environment flow](ENVIRONMENTS.md) for the
  `dev` to `staging` to `prod` promotion model.

For day-to-day commands, run `make help` from the repository root. Application
features such as the CLI and orchestrator are delegated to `src/launch`, while
installation, tests, services, builds, and documentation remain root-owned.
