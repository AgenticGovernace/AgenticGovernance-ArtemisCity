# agentic_governance_artemis_city

Artemis City is an architectural framework designed to align agentic reasoning with transparent, accountable action across distributed intelligence systems—both human and machine. The project is founded on the principles of iterative clarity and accountable collaboration, balancing trust, entropy, and coordination to advance a “net good over noise” ethos.

This project establishes a governance framework for large-scale multi-agent deployments in which transparency is intrinsic rather than retrospective. It advances a structured approach to building agents for real-world applications by conceptualizing each task or prompt within a large language model (LLM) system as a formal directive, with responsibilities distributed accordingly. Absent such rigor and determinism, the potential benefits of artificial intelligence risk dilution.

Artemis City illustrates a standardized model that can be replicated across domains without compromising efficiency or transparency. For AI systems to achieve broad enterprise adoption, these forces must be aligned. The framework emphasizes disciplined experimentation, public learning, and responsible iteration, recognizing that progress emerges through refinement, measured failure, and principled accountability.

Artemis City is introduced as a new class of agentic operating system (AOS) for autonomous AI networks. It extends beyond conventional agent wrappers by providing a comprehensive infrastructure architecture for coordinating multiple intelligent agents, maintaining persistent memory, and enabling adaptive learning.

Its primary differentiators lie in how artificial intelligence systems reason, execute decisions, and incorporate feedback from outcomes. This repository presents demonstrations of these concepts, drawing on biological principles to enhance the deployment of large language models (LLMs) with reduced cost and improved accuracy. These improvements are achieved through the integration of information acquisition and control (IAC) and infrastructure as code (IaC).

# MCP - Multi-Agent Coordination Platform
A multi-agent orchestration system built around an **Obsidian vault as persistent memory**. Agents communicate via the **Artemis Transmission Protocol (ATP)**, are ranked by **Hebbian-weighted trust scores**, and route tasks through a central orchestrator. A write-through memory bus keeps the vault and a local vector store in sync for both auditable storage and fast semantic recall.

## System Architecture
```mermaid
graph TB
subgraph User["User Layer"]
    CLI["main.py<br/>CLI Entrypoint"]
    WebUI["web/<br/>FastAPI + React Dashboard"]
end

subgraph Orchestration["Orchestration Layer"]
    ORC["Orchestrator<br/>Task routing & dispatch"]
    REG["Agent Registry<br/>Alignment · Accuracy · Efficiency"]
    HEB["Hebbian Weights<br/>Adaptive scoring"]
end

subgraph Agents["Agent Layer"]
    ART["Artemis Agent<br/>Governance & Audit"]
    RES["Research Agent<br/>Web Search"]
    SUM["Summarizer Agent<br/>Text Condensation"]
    PLN["Planner Agent<br/>Architecture & Context"]
end

subgraph Protocol["Communication Layer"]
    ATP["ATP Protocol<br/>Mode · Priority · Action · Context"]
    TRUST["Trust Interface<br/>Score decay & permissions"]
    GOV["Governance Monitor<br/>Failure tracking & rollback"]
end

subgraph Memory["Memory Layer"]
    OBS["Obsidian Vault<br/>Agent Inputs/ · Agent Outputs/"]
    VEC["Vector Store<br/>Semantic search"]
    BUS["Memory Bus<br/>Write-through sync"]
    POST["Postal Service<br/>Inter-agent mail routing"]
end

CLI --> ORC
WebUI --> ORC
ORC --> REG
ORC --> HEB
REG --> ART & RES & SUM & PLN
ART & RES & SUM & PLN --> ATP
ATP --> TRUST
TRUST --> GOV
ART & RES & SUM & PLN --> POST
POST --> BUS
BUS --> OBS
BUS --> VEC
```
## Quick Start
```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure vault path
cp .env.example .env           # then set OBSIDIAN_VAULT_PATH

# 3. Run the platform
python main.py                              # full run with demo tasks
python main.py --skip-demos                 # skip demo note creation
python main.py -i "Summarize X" -c text_summarization
python main.py --agent research_agent -i "Research Y"
python main.py --show-hebbian               # view Hebbian network summary
python main.py --agent-stats artemis        # single-agent stats
```
## Key Concepts
| Concept | Description |
| ----- | ----- |
| **ATP** | <p>Structured message headers (</p><p>, </p><p>, </p><p>, </p><p>) parsed by agents to determine intent and routing</p> |
| **Hebbian Weights** | Agents gain or lose routing priority based on task success/failure history — "neurons that fire together wire together" |
| **Trust Decay** | Agent trust scores decay over time without reinforcement, gating read/write/delete permissions |
| **Memory Bus** | Write-through layer keeping the Obsidian vault (auditable) and vector store (fast semantic recall) in sync |
| **Postal Service** | Inter-agent communication framed as mail delivery — agents are citizens, the vault is the City Archives |
| **Governance Monitor** | Tracks memory-bus failures and emits rollback signals when thresholds are exceeded |
| **Orchestrator** | <p>Reads pending tasks from </p><p>, matches </p><p> to the highest-scored agent, executes, writes results to </p> |
## Concept Demos
Interactive browser prototypes and CLI walkthroughs in [﻿Concept_Demos/](Concept_Demos/README.md). Deployed to Vercel as a static site.

| Demo | Type | What it shows |
| ----- | ----- | ----- |
|  | Browser | ATP message builder, agent routing simulation, trust decay chart with scenario switching |
|  | Browser | Hebbian learning network — agent weights, reinforcement dynamics, live simulation |
|  | CLI | ATP parsing, instruction loading, persona modes, reflection engine, semantic tagging |
|  | CLI | Inter-agent mail, archive filing, trust clearances (works offline with mocks) |
|  | CLI | MCP server connection, trust interface, context loading from Obsidian, trust decay model |
```bash
# Browser demos — serve locally
cd Concept_Demos && python -m http.server 8080
# Then open http://localhost:8080

# CLI demos — run from repo root
python Concept_Demos/demo_artemis.py
python Concept_Demos/demo_city_postal.py
python Concept_Demos/demo_memory_integration.py
```
## Tests
```bash
pytest tests/
```
## Author
Prinston (Apollo) Palmer - Systems Architect



<!--- Eraser file: https://app.eraser.io/workspace/B3mWQIytmT8waGacSoVV --->
