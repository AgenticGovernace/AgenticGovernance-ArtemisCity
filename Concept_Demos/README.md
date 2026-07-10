<p><a target="_blank" href="https://app.eraser.io/workspace/RVDoAByzCOIrkkYGNG0g" id="edit-in-eraser-github-link"><img alt="Edit in Eraser" src="https://firebasestorage.googleapis.com/v0/b/second-petal-295822.appspot.com/o/images%2Fgithub%2FOpen%20in%20Eraser.svg?alt=media&amp;token=968381c8-a7e7-472a-8ed6-4a6626da5501"></a></p>

# Concept Demos
Interactive browser prototypes for Artemis City. This directory is kept as a
static demo gallery plus compatibility shims for older CLI commands.

Maintained Python walkthroughs now live under `src/launch/`, and the production
runtime lives under `src/`. Do not add new Python implementation modules here.

## Contents
| File | Type | Description |
| ----- | ----- | ----- |
| `index.html`  | Landing page | Card-based hub linking to all demos with run instructions |
| `atp_prototype.html`  | Browser (React) | ATP message builder, keyword-based agent routing sim, trust decay chart with 4 scenarios |
| `Hebbian_Proto.html`  | Browser (React) | Hebbian learning network — agent weight evolution, reinforcement dynamics, live sim |
| `demo_artemis.py`  | CLI shim | Forwards to `src/launch/demo_artemis.py` |
| `demo_city_postal.py`  | CLI shim | Forwards to `src/launch/demo_city_postal.py` |
| `demo_memory_integration.py`  | CLI shim | Forwards to `src/launch/demo_memory_integration.py` |
## Browser Demos
### ATP Prototype (`atp_prototype.html`)
Four interactive tabs:

1. **Message Builder** - compose ATP headers (`#Mode`  , `#Priority`  , `#ActionType`  , `#Context`  , `#TargetZone`  ) with real-time validation
2. **Agent Routing** - enter context text and watch keyword matching route to Artemis, Planner, Pack Rat, or Daemon Daemon
3. **Trust Decay** - area chart showing trust score over 30 days across 4 scenarios (natural decay, positive reinforcement, violation, recovery)
4. **Full Workflow** - animated 5-step walk-through of the ATP message life-cycle from composition through trust update
### Hebbian Network (`Hebbian_Proto.html`)
Live visualization of agent Hebbian weights, connection strengths, and reinforcement events.

## Running
### Browser demos
```bash
# Serve from Concept_Demos directory
cd Concept_Demos && python -m http.server 8080

# Then open:
#   http://localhost:8080                    Landing page
#   http://localhost:8080/atp_prototype.html ATP prototype
#   http://localhost:8080/Hebbian_Proto.html Hebbian network
```
### CLI walkthroughs
Run the maintained entry points from the repo root:

```bash
# Artemis persona + ATP + reflection (interactive, step-through with Enter prompts)
python src/launch/demo_artemis.py

# City postal service (works offline with mock post office and trust interface)
python src/launch/demo_city_postal.py

# Memory integration (skips MCP-only flows gracefully if server is unavailable)
python src/launch/demo_memory_integration.py
```

The historical `python Concept_Demos/demo_*.py` commands still work through
compatibility shims, but they are not the source of truth.




<!--- Eraser file: https://app.eraser.io/workspace/RVDoAByzCOIrkkYGNG0g --->
