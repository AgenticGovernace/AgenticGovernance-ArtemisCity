"""Narrative simulation for Sandbox City (Artemis City metaphor).

Think "The Sims" but mapped to Artemis City concepts: governance (Town Hall),
memory (Library), delivery (Post Office), monitoring (Watchtower), and the
public interface (Public Square). The loop is intentionally lightweight so it
can run in constrained environments or be embedded into other agents/tests.

Run it directly:
    python app/sandbox_city/run_simulation.py --ticks 16 --seed 42
"""

from __future__ import annotations

import argparse
import json
import random
import textwrap
from dataclasses import dataclass, field
from typing import Dict, List, Optional


def clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    """Clamp a numeric value into the inclusive [minimum, maximum] range."""
    return max(minimum, min(maximum, value))


@dataclass
class ZoneState:
    """Represents a functional zone inside Sandbox City."""

    name: str
    role: str
    description: str
    stability: float = 0.8  # Resilience of the zone infrastructure
    load: float = 0.35  # Operational load / queue pressure
    risk: float = 0.12  # Latent risk / anomaly likelihood

    def apply_delta(self, stability: float = 0.0, load: float = 0.0, risk: float = 0.0) -> None:
        """Adjust metrics while keeping them within sane bounds."""
        self.stability = clamp(self.stability + stability)
        self.load = clamp(self.load + load)
        self.risk = clamp(self.risk + risk)

    def as_dict(self) -> Dict[str, float]:
        return {
            "stability": round(self.stability, 3),
            "load": round(self.load, 3),
            "risk": round(self.risk, 3),
        }


@dataclass
class Resident:
    """A resident/agent acting inside the city."""

    name: str
    role: str
    focus_zone: str
    morale: float = 0.72
    energy: float = 0.72
    trust: float = 0.78

    def apply_delta(self, morale: float = 0.0, energy: float = 0.0, trust: float = 0.0) -> None:
        self.morale = clamp(self.morale + morale)
        self.energy = clamp(self.energy + energy)
        self.trust = clamp(self.trust + trust)

    def as_dict(self) -> Dict[str, float]:
        return {
            "morale": round(self.morale, 3),
            "energy": round(self.energy, 3),
            "trust": round(self.trust, 3),
            "role": self.role,
            "focus_zone": self.focus_zone,
        }


@dataclass
class CityEvent:
    """Discrete event that perturbs the simulation."""

    name: str
    zone: str
    severity: float
    narrative: str
    positive: bool = False

    def apply_to_zone(self, zone_state: ZoneState) -> None:
        """Modify zone metrics based on severity and polarity."""
        sign = 1 if self.positive else -1
        zone_state.apply_delta(
            stability=sign * -0.35 * self.severity,  # Negative for incidents, positive for boosts
            load=0.45 * self.severity,
            risk=0.40 * self.severity * (1 if not self.positive else -0.5),
        )


@dataclass
class ActionResult:
    """Outcome of a resident action for logging and state introspection."""

    actor: str
    action: str
    zone: Optional[str]
    summary: str


class CitySimulation:
    """Lightweight narrative simulation loop."""

    def __init__(self, seed: Optional[int] = None) -> None:
        self.random = random.Random(seed)
        self.tick: int = 0
        self.zones: Dict[str, ZoneState] = self._default_zones()
        self.residents: List[Resident] = self._default_residents()
        self.history: List[Dict[str, object]] = []  # Snapshots per tick for offline analysis

    # ---- Public API -----------------------------------------------------

    def run(self, ticks: int = 12, verbose: bool = True, summary_every: int = 1, json_out: Optional[str] = None) -> Dict[str, object]:
        """Advance the simulation for `ticks` steps."""
        for _ in range(ticks):
            self.tick += 1
            events = self._spawn_events()
            actions = [self._take_action(resident, events) for resident in self.residents]
            snapshot = self._snapshot(events=events, actions=actions)
            self.history.append(snapshot)

            if verbose and self.tick % summary_every == 0:
                self._print_tick(snapshot)

        if json_out:
            with open(json_out, "w", encoding="utf-8") as f:
                json.dump(self.history, f, indent=2)

        return self.history[-1] if self.history else {}

    # ---- Simulation internals ------------------------------------------

    def _spawn_events(self) -> List[CityEvent]:
        """Probabilistically create city events."""
        events: List[CityEvent] = []
        if self.random.random() < 0.35:
            events.append(self.random.choice(self._event_catalog()))
        # Rare chance for a second concurrent event
        if self.random.random() < 0.10:
            events.append(self.random.choice(self._event_catalog()))

        for event in events:
            zone = self.zones.get(event.zone)
            if zone:
                event.apply_to_zone(zone)
                # Residents tied to the zone feel immediate impact
                for resident in self.residents:
                    if resident.focus_zone == event.zone:
                        swing = 0.18 * event.severity
                        if event.positive:
                            resident.apply_delta(morale=swing, trust=swing * 0.6, energy=0.05)
                        else:
                            resident.apply_delta(morale=-swing, trust=-0.5 * swing, energy=-0.08)
        return events

    def _take_action(self, resident: Resident, events: List[CityEvent]) -> ActionResult:
        """Decide and apply a resident's action for the current tick."""
        # Priority 1: recover if exhausted
        if resident.energy < 0.28:
            return self._rest(resident)

        # Priority 2: respond to incidents in their zone
        event_zones = {event.zone for event in events if not event.positive}
        if resident.focus_zone in event_zones:
            return self._stabilize_zone(resident, self.zones[resident.focus_zone])

        # Priority 3: reduce overload in their home zone
        home_zone = self.zones[resident.focus_zone]
        if home_zone.load > 0.65:
            return self._process_backlog(resident, home_zone)

        # Priority 4: morale maintenance
        if resident.morale < 0.4:
            return self._socialize(resident)

        # Default: do role-specific work
        return self._role_action(resident, home_zone)

    def _role_action(self, resident: Resident, zone: ZoneState) -> ActionResult:
        if "Artemis" in resident.name:
            return self._audit(resident, zone)
        if "Pack Rat" in resident.name:
            return self._deliver_mail(resident, zone)
        if "Codex" in resident.name:
            return self._index_memory(resident, zone)
        if "Sentinel" in resident.name:
            return self._patrol(resident, zone)
        if "Workshop" in resident.role:
            return self._prototype(resident, zone)
        return self._socialize(resident)

    # ---- Action implementations ----------------------------------------

    def _rest(self, resident: Resident) -> ActionResult:
        resident.apply_delta(energy=0.22, morale=0.05)
        return ActionResult(
            actor=resident.name,
            action="rest",
            zone=None,
            summary="recovered energy and composure",
        )

    def _stabilize_zone(self, resident: Resident, zone: ZoneState) -> ActionResult:
        zone.apply_delta(stability=0.12, risk=-0.08, load=-0.05)
        resident.apply_delta(trust=0.05, energy=-0.08)
        return ActionResult(
            actor=resident.name,
            action="stabilize",
            zone=zone.name,
            summary=f"contained incident in {zone.name}",
        )

    def _process_backlog(self, resident: Resident, zone: ZoneState) -> ActionResult:
        zone.apply_delta(load=-0.15, stability=0.03)
        resident.apply_delta(energy=-0.06, morale=0.02, trust=0.01)
        return ActionResult(
            actor=resident.name,
            action="workload-burn",
            zone=zone.name,
            summary=f"burned down queue in {zone.name}",
        )

    def _socialize(self, resident: Resident) -> ActionResult:
        resident.apply_delta(morale=0.14, trust=0.06, energy=-0.04)
        public_square = self.zones.get("Public Square")
        if public_square:
            public_square.apply_delta(stability=0.02, risk=-0.03)
        return ActionResult(
            actor=resident.name,
            action="socialize",
            zone="Public Square",
            summary="reconnected in the Public Square",
        )

    def _audit(self, resident: Resident, zone: ZoneState) -> ActionResult:
        zone.apply_delta(stability=0.05, risk=-0.05, load=0.03)
        resident.apply_delta(trust=0.08, energy=-0.05)
        return ActionResult(
            actor=resident.name,
            action="audit",
            zone=zone.name,
            summary="ran a governance audit",
        )

    def _deliver_mail(self, resident: Resident, zone: ZoneState) -> ActionResult:
        zone.apply_delta(load=-0.08, stability=0.02, risk=-0.02)
        resident.apply_delta(energy=-0.04, morale=0.04)
        return ActionResult(
            actor=resident.name,
            action="deliver-mail",
            zone=zone.name,
            summary="cleared secure message backlog",
        )

    def _index_memory(self, resident: Resident, zone: ZoneState) -> ActionResult:
        zone.apply_delta(stability=0.06, risk=-0.03, load=-0.04)
        resident.apply_delta(trust=0.07, energy=-0.05)
        return ActionResult(
            actor=resident.name,
            action="index-memory",
            zone=zone.name,
            summary="tightened memory indices",
        )

    def _patrol(self, resident: Resident, zone: ZoneState) -> ActionResult:
        zone.apply_delta(risk=-0.07, stability=0.02, load=-0.02)
        resident.apply_delta(trust=0.04, energy=-0.04)
        return ActionResult(
            actor=resident.name,
            action="patrol",
            zone=zone.name,
            summary="patrolled the Watchtower perimeter",
        )

    def _prototype(self, resident: Resident, zone: ZoneState) -> ActionResult:
        zone.apply_delta(stability=0.03, load=0.04, risk=0.02)
        resident.apply_delta(energy=-0.05, morale=0.08, trust=0.03)
        return ActionResult(
            actor=resident.name,
            action="prototype",
            zone=zone.name,
            summary="shipped a rapid prototype",
        )

    # ---- Snapshot + catalog helpers ------------------------------------

    def _snapshot(self, events: List[CityEvent], actions: List[ActionResult]) -> Dict[str, object]:
        scores = self._city_scores()
        return {
            "tick": self.tick,
            "events": [
                {
                    "name": event.name,
                    "zone": event.zone,
                    "severity": event.severity,
                    "positive": event.positive,
                    "narrative": event.narrative,
                }
                for event in events
            ],
            "actions": [action.__dict__ for action in actions],
            "zones": {name: zone.as_dict() for name, zone in self.zones.items()},
            "residents": {resident.name: resident.as_dict() for resident in self.residents},
            "scores": scores,
        }

    def _city_scores(self) -> Dict[str, float]:
        stability = sum(zone.stability for zone in self.zones.values()) / len(self.zones)
        load = sum(zone.load for zone in self.zones.values()) / len(self.zones)
        risk = sum(zone.risk for zone in self.zones.values()) / len(self.zones)
        morale = sum(resident.morale for resident in self.residents) / len(self.residents)
        trust = sum(resident.trust for resident in self.residents) / len(self.residents)
        energy = sum(resident.energy for resident in self.residents) / len(self.residents)
        return {
            "service_health": round(stability * (1 - load) * (1 - risk), 3),
            "stability": round(stability, 3),
            "load": round(load, 3),
            "risk": round(risk, 3),
            "morale": round(morale, 3),
            "trust": round(trust, 3),
            "energy": round(energy, 3),
        }

    def _event_catalog(self) -> List[CityEvent]:
        return [
            CityEvent("Policy backlog", "Town Hall", severity=0.22, narrative="Audit queue piles up after a spike in edge-cases."),
            CityEvent("Packet storm", "Post Office", severity=0.18, narrative="Burst of encrypted traffic saturates the secure channels."),
            CityEvent("Data drift alert", "Library", severity=0.20, narrative="Checksum drift detected in historical archives."),
            CityEvent("Sensor false alarm", "Watchtower", severity=0.14, narrative="False positive anomaly causes alert churn."),
            CityEvent("Prototype sprint", "Workshop", severity=0.16, narrative="Ambitious sprint strains tooling and review bandwidth."),
            CityEvent("Public rumor", "Public Square", severity=0.15, narrative="Rumor spreads about policy change; clarifications needed."),
            CityEvent("Block party", "Public Square", severity=0.14, narrative="Spontaneous gathering boosts spirits and trust.", positive=True),
            CityEvent("Mentorship hour", "Library", severity=0.12, narrative="Knowledge share boosts memory hygiene.", positive=True),
        ]

    @staticmethod
    def _default_zones() -> Dict[str, ZoneState]:
        return {
            "Town Hall": ZoneState("Town Hall", "Governance Hub", "Policy, audits, and arbitration", stability=0.82, load=0.42, risk=0.10),
            "Post Office": ZoneState("Post Office", "Secure Load Zone", "Encrypted data transfer via Pack Rat", stability=0.78, load=0.37, risk=0.14),
            "Library": ZoneState("Library", "Memory Archives", "Persistent memory stack and indexing", stability=0.80, load=0.40, risk=0.12),
            "Workshop": ZoneState("Workshop", "Agent Development & Testing", "Prototyping, validation sims, onboarding", stability=0.76, load=0.38, risk=0.16),
            "Public Square": ZoneState("Public Square", "Interface Layer", "Human/agent interaction surface", stability=0.79, load=0.33, risk=0.10),
            "Watchtower": ZoneState("Watchtower", "Monitoring & Logging", "System monitoring, anomaly detection", stability=0.81, load=0.36, risk=0.13),
        }

    @staticmethod
    def _default_residents() -> List[Resident]:
        return [
            Resident(name="Artemis (Governor)", role="Governance steward", focus_zone="Town Hall", trust=0.83),
            Resident(name="Pack Rat Courier", role="Secure courier", focus_zone="Post Office", energy=0.75),
            Resident(name="Codex Daemon", role="Memory caretaker", focus_zone="Library", trust=0.85),
            Resident(name="Workshop Lead", role="Workshop engineer", focus_zone="Workshop", morale=0.76),
            Resident(name="Sentinel Scout", role="Watchtower monitor", focus_zone="Watchtower", energy=0.74),
            Resident(name="Public Liaison", role="Community interface", focus_zone="Public Square", morale=0.78),
        ]

    # ---- Presentation helpers ------------------------------------------

    def _print_tick(self, snapshot: Dict[str, object]) -> None:
        events = snapshot["events"]
        actions = snapshot["actions"]
        scores = snapshot["scores"]

        print(f"\n=== Tick {snapshot['tick']:02d} ===")
        if events:
            for event in events:
                polarity = "⭐" if event["positive"] else "⚠️"
                print(f"{polarity} {event['name']} at {event['zone']} (sev {event['severity']:.2f}) — {event['narrative']}")
        else:
            print("… No city events")

        for action in actions:
            location = f" @ {action['zone']}" if action["zone"] else ""
            print(f"• {action['actor']} {action['summary']}{location}")

        print(
            textwrap.dedent(
                f"""
                Scores: service_health={scores['service_health']:.3f} | stability={scores['stability']:.2f} | load={scores['load']:.2f} | risk={scores['risk']:.2f}
                        morale={scores['morale']:.2f} | trust={scores['trust']:.2f} | energy={scores['energy']:.2f}
                """
            ).strip()
        )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Sandbox City (Artemis City) simulation loop.")
    parser.add_argument("--ticks", type=int, default=12, help="Number of ticks (steps) to simulate.")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducible runs.")
    parser.add_argument("--summary-every", type=int, default=1, help="Print every Nth tick (default: 1).")
    parser.add_argument("--json-out", type=str, default=None, help="Optional path to dump the tick-by-tick state as JSON.")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    sim = CitySimulation(seed=args.seed)
    sim.run(ticks=args.ticks, verbose=True, summary_every=args.summary_every, json_out=args.json_out)
