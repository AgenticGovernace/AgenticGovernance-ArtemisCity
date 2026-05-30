/**
 * Registry Controller
 *
 * Bridges the HTTP layer to the authoritative Python agent registry
 * (src/integration/agent_registry.py) via the Python JSON bridge. Replaces
 * the in-memory agent stubs for the governance surface: trust tiers,
 * violation tracking, and quarantine.
 */

import { callBridge } from '../lib/pythonBridge';

export class RegistryController {
  /** List all registered agents with scores + governance state. */
  async listAgents(): Promise<any> {
    return callBridge('registry.list_agents');
  }

  /** Get one agent's full record (scores + governance), or 404. */
  async getAgent(agentName: string): Promise<any> {
    return callBridge('registry.get_agent', { name: agentName });
  }

  /** Get an agent's violations and current quarantine state. */
  async getViolations(
    agentName: string,
    includeCleared = false,
    limit = 100
  ): Promise<any> {
    return callBridge('registry.get_violations', {
      name: agentName,
      include_cleared: includeCleared,
      limit,
    });
  }

  /** Clear an agent's violations, release quarantine, optionally re-tier. */
  async clearViolations(
    agentName: string,
    rationale: string,
    overrideTier?: string
  ): Promise<any> {
    return callBridge('registry.clear_violations', {
      name: agentName,
      rationale,
      override_tier: overrideTier ?? null,
    });
  }

  /** Set an agent's trust tier (auto|monitored|human). */
  async setTrustTier(agentName: string, tier: string): Promise<any> {
    return callBridge('registry.set_trust_tier', { name: agentName, tier });
  }
}
