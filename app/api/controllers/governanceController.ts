/**
 * Governance Controller
 *
 * Bridges the HTTP layer to the Python governance engine: trust-score
 * computation (weighted formula from GOVERNANCE.md) and self-update approval
 * tier classification (auto | monitored | human).
 */

import { callBridge } from '../lib/pythonBridge';

export interface TrustMetricsInput {
  successful_executions?: number;
  total_executions?: number;
  recent_violation_count?: number;
  coverage_ratio?: number;
  passed_lints?: boolean;
  no_dead_code?: boolean;
  approved_updates?: number;
  total_update_attempts?: number;
  downtime_hours?: number;
  total_hours?: number;
}

export interface UpdateProposalInput {
  trust_score?: number;
  metrics?: TrustMetricsInput;
  has_history?: boolean;
  code_change_ratio?: number;
  breaking_changes?: boolean;
  new_dependencies?: boolean;
  policy_change?: boolean;
  affects_governance?: boolean;
}

/**
 * Controller responsible for proxying governance calculations and update evaluations to the Python bridge.
 */
export class GovernanceController {
  /**
   * Compute (and optionally persist) an agent's trust score from metrics.
   * Missing `recent_violation_count` is filled from the registry.
   */
  async computeTrust(
    agentName: string,
    metrics: TrustMetricsInput = {},
    persist = true
  ): Promise<any> {
    return callBridge('governance.compute_trust', {
      name: agentName,
      metrics,
      persist,
    });
  }

  /**
   * Classify a proposed self-update into an approval tier. Trust is taken
   * from `trust_score`, else computed from `metrics`, else the persisted
   * registry value.
   *
   * @param agentName - Agent name to forward to the Python bridge.
   * @param proposal - Update proposal payload to classify.
   * @returns Promise resolving to the operation result produced by classifying a proposed self-update into an approval tier. Trust is taken.
   */
  async evaluateUpdate(agentName: string, proposal: UpdateProposalInput): Promise<any> {
    return callBridge('governance.evaluate_update', {
      agent_name: agentName,
      ...proposal,
    });
  }

  async recordViolation(
    agentName: string,
    violationType: string,
    details: Record<string, unknown> = {}
  ): Promise<any> {
    return callBridge('registry.record_violation', {
      name: agentName,
      violation_type: violationType,
      details,
    });
  }

  async setTrustTier(agentName: string, tier: string): Promise<any> {
    return callBridge('registry.set_trust_tier', {
      name: agentName,
      tier,
    });
  }
}
