# MCP Common Quarantine

This package is a dormant incubator. It is not production authentication. It is not production authorization. It is not production routing. It is not principal authority.

The current `GovernedGate` accepts a caller-selected capability. Production governance
must derive capability decisions from a server-owned ATP operation mapping instead of
trusting a caller to choose the required capability.

This remains quarantined: production wiring and publication are forbidden until the governed-core replacement/adapters are reviewed and the release allowlists explicitly admit the maintained surface.
