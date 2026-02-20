# Concept Demos

Interactive browser prototypes and CLI walkthroughs for the MCP platform. The browser demos are self-contained (CDN React + Tailwind + Recharts) and deploy to Vercel as a static site. Python demos run from the repo root.

## Contents

| File | Type | Description |
|---|---|---|
| `index.html` | Landing page | Card-based hub linking to all demos with run instructions |
| `atp-prototype.html` | Browser (React) | ATP message builder, keyword-based agent routing sim, trust decay chart with 4 scenarios |
| `Hebbian_Proto.html` | Browser (React) | Hebbian learning network — agent weight evolution, reinforcement dynamics, live sim |
| `demo_artemis.py` | CLI | ATP parsing, instruction hierarchy loading, persona response modes, reflection engine, semantic tagging with citations |
| `demo_city_postal.py` | CLI | Inter-agent mail delivery, mailbox checks, City Archives filing, trust clearance matrix (works offline via mocks) |
| `demo_memory_integration.py` | CLI | MCP server health check, trust interface with permission matrix, Obsidian context loading, integrated agent-vault workflow, trust decay model |
| `atp-prototype.jsx` | Source | React component source for the ATP prototype (reference only) |
| `vercel.json` | Config | Static deploy config with clean URL rewrites |

## Browser Demos

### ATP Prototype (`atp-prototype.html`)

Four interactive tabs:

1. **Message Builder** - compose ATP headers (`#Mode`, `#Priority`, `#ActionType`, `#Context`, `#TargetZone`) with real-time validation
2. **Agent Routing** - enter context text and watch keyword matching route to Artemis, Planner, Pack Rat, or Codex Daemon
3. **Trust Decay** - area chart showing trust score over 30 days across 4 scenarios (natural decay, positive reinforcement, violation, recovery)
4. **Full Workflow** - animated 5-step walkthrough of the ATP message lifecycle from composition through trust update

### Hebbian Network (`Hebbian_Proto.html`)

Live visualization of agent Hebbian weights, connection strengths, and reinforcement events.

## Prerequisites

- Python 3.9+
- `pip install -r requirements.txt` (from repo root)
- **Memory demo only**: `MCP_BASE_URL` and `MCP_API_KEY` env vars, MCP server running

## Running

### Browser demos

```bash
# Serve from Concept_Demos directory
cd Concept_Demos && python -m http.server 8080

# Then open:
#   http://localhost:8080                    Landing page
#   http://localhost:8080/atp-prototype.html ATP prototype
#   http://localhost:8080/Hebbian_Proto.html Hebbian network
```

### CLI demos

Run from the repo root so imports resolve:

```bash
# Artemis persona + ATP + reflection (interactive, step-through with Enter prompts)
python Concept_Demos/demo_artemis.py

# City postal service (works offline with mock post office and trust interface)
python Concept_Demos/demo_city_postal.py

# Memory integration (skips MCP-only flows gracefully if server is unavailable)
python Concept_Demos/demo_memory_integration.py
```

## Deploy (Vercel)

A `vercel.json` is included with clean URLs and short aliases.

```bash
cd Concept_Demos
vercel            # preview deploy
vercel --prod     # production deploy
```

Once deployed:
- `/` - Landing page
- `/atp` - ATP prototype
- `/hebbian` - Hebbian network visualization
