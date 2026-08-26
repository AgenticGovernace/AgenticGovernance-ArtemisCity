/**
 * Trust Controller
 *
 * Trust and violation operations backed by Python governance/registry bridge
 * commands. No TypeScript-local trust or Hebbian state is authoritative.
 */

import { callBridge } from "../lib/pythonBridge";

export class TrustController {
  async getTrustScore(entityId: string): Promise<unknown> {
    return callBridge("trust.get_score", { entity_id: entityId });
  }

  async setTrustScore(
    entityId: string,
    score: number,
    entityType = "agent",
  ): Promise<unknown> {
    return callBridge("trust.set_score", {
      entity_id: entityId,
      entity_type: entityType,
      score,
    });
  }

  async recordSuccess(entityId: string, amount = 0.02): Promise<unknown> {
    return callBridge("trust.record_success", {
      entity_id: entityId,
      amount,
    });
  }

  async recordFailure(entityId: string, amount = 0.05): Promise<unknown> {
    return callBridge("trust.record_failure", {
      entity_id: entityId,
      amount,
    });
  }

  async getPermissions(entityId: string): Promise<unknown> {
    return callBridge("trust.permissions", { entity_id: entityId });
  }

  async canPerformOperation(
    entityId: string,
    operation: string,
  ): Promise<unknown> {
    return callBridge("trust.can_perform", {
      entity_id: entityId,
      operation,
    });
  }

  async getHebbianWeights(): Promise<unknown> {
    return callBridge("hebbian.weights");
  }

  async getHebbianSentinelStatus(
    agentName?: string,
    taskType?: string,
    limit = 100,
  ): Promise<unknown> {
    return callBridge("hebbian.sentinel_status", {
      agent_name: agentName,
      task_type: taskType,
      limit,
    });
  }

  async getHebbianSentinelAlerts(
    openOnly = false,
    limit = 100,
  ): Promise<unknown> {
    return callBridge("hebbian.sentinel_alerts", {
      open_only: openOnly,
      limit,
    });
  }

  async updateHebbianWeight(
    agent1: string,
    agent2: string,
    delta: number,
  ): Promise<unknown> {
    return callBridge("hebbian.update", {
      agent1,
      agent2,
      delta,
    });
  }

  async getTrustReport(): Promise<unknown> {
    return callBridge("trust.report");
  }

  async applyDecay(decayRate = 0.01): Promise<unknown> {
    return callBridge("trust.apply_decay", { decay_rate: decayRate });
  }

  async getTrustLevels(): Promise<unknown> {
    return callBridge("trust.levels");
  }
}
