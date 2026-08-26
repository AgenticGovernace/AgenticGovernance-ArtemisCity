/**
 * Registry Controller
 *
 * Bridges the HTTP layer to the authoritative Python agent registry
 * (src/integration/agent_registry.py) via the Python JSON bridge. Replaces
 * the in-memory agent stubs for the governance surface: trust tiers,
 * violation tracking, and quarantine.
 */

import { callBridge } from "../lib/pythonBridge";

/**
 * Controller responsible for proxying registry operations to the Python bridge.
 */
export class RegistryController {
  /** List all registered agents with scores + governance state. */
  /**
   * List agents.
   *
   * @returns Promise resolving to the operation result produced by listing agents.
   */
  async listAgents(): Promise<any> {
    return callBridge("registry.list_agents");
  }

  /** Get one agent's full record (scores + governance), or 404. */
  /**
   * Get agent.
   *
   * @param agentName - Agent name to forward to the Python bridge.
   * @returns Promise resolving to the operation result produced by getting agent.
   */
  async getAgent(agentName: string): Promise<any> {
    return callBridge("registry.get_agent", { name: agentName });
  }

  /** Get an agent's violations and current quarantine state. */
  /**
   * Get violations.
   *
   * @param agentName - Agent name to forward to the Python bridge.
   * @param includeCleared - Include cleared value used by this operation.
   * @param limit - Maximum number of items to include in the result.
   * @returns Promise resolving to the operation result produced by getting violations.
   */
  async getViolations(
    agentName: string,
    includeCleared = false,
    limit = 100,
  ): Promise<any> {
    return callBridge("registry.get_violations", {
      name: agentName,
      include_cleared: includeCleared,
      limit,
    });
  }

  /** Clear an agent's violations, release quarantine, optionally re-tier. */
  /**
   * Clear violations.
   *
   * @param agentName - Agent name to forward to the Python bridge.
   * @param rationale - Rationale value used by this operation.
   * @param overrideTier - Override tier value used by this operation.
   * @returns Promise resolving to the operation result produced by clearing violations.
   */
  async clearViolations(
    agentName: string,
    rationale: string,
    overrideTier?: string,
  ): Promise<any> {
    return callBridge("registry.clear_violations", {
      name: agentName,
      rationale,
      override_tier: overrideTier ?? null,
    });
  }

  /** Set an agent's trust tier (auto|monitored|human). */
  /**
   * Set trust tier.
   *
   * @param agentName - Agent name to forward to the Python bridge.
   * @param tier - Tier value used by this operation.
   * @returns Promise resolving to the operation result produced by setting trust tier.
   */
  async setTrustTier(agentName: string, tier: string): Promise<any> {
    return callBridge("registry.set_trust_tier", { name: agentName, tier });
  }
}
