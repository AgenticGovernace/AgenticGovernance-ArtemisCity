/**
 * Agent Controller
 *
 * Read-only agent facade backed by the authoritative Python registry.
 */

import { callBridge } from '../lib/pythonBridge';

type AgentRecord = Record<string, unknown> & {
  name?: string;
  capabilities?: string[];
  trust_score?: number | null;
  trust_tier?: string | null;
  status?: string | null;
};

interface AgentListResponse {
  agents?: AgentRecord[];
  total?: number;
}

export class AgentController {
  async getAllAgents(): Promise<AgentRecord[]> {
    const data = (await callBridge('registry.list_agents')) as AgentListResponse;
    return Array.isArray(data.agents) ? data.agents : [];
  }

  async getAgent(id: string): Promise<AgentRecord> {
    return (await callBridge('registry.get_agent', { name: id })) as AgentRecord;
  }

  async registerAgent(agentData: Partial<AgentRecord>): Promise<AgentRecord> {
    return (await callBridge('registry.register_agent', agentData)) as AgentRecord;
  }

  async updateAgent(id: string, updates: Partial<AgentRecord>): Promise<AgentRecord> {
    return (await callBridge('registry.update_agent', { name: id, updates })) as AgentRecord;
  }

  async deleteAgent(id: string): Promise<unknown> {
    return callBridge('registry.delete_agent', { name: id });
  }

  async suspendAgent(id: string, reason?: string): Promise<AgentRecord> {
    return (await callBridge('registry.set_agent_status', {
      name: id,
      status: 'suspended',
      reason,
    })) as AgentRecord;
  }

  async activateAgent(id: string): Promise<AgentRecord> {
    return (await callBridge('registry.set_agent_status', {
      name: id,
      status: 'active',
    })) as AgentRecord;
  }

  async getAgentCard(id: string): Promise<{ markdown: string; agent: AgentRecord }> {
    const agent = await this.getAgent(id);
    const name = String(agent.name ?? id);
    const capabilities = Array.isArray(agent.capabilities)
      ? agent.capabilities.join(', ')
      : '';
    const trust =
      typeof agent.trust_score === 'number'
        ? agent.trust_score.toFixed(3)
        : String(agent.trust_tier ?? 'unknown');
    const status = String(agent.status ?? 'unknown');

    return {
      agent,
      markdown: [
        `# ${name}`,
        '',
        `- Status: ${status}`,
        `- Trust: ${trust}`,
        `- Capabilities: ${capabilities || 'none declared'}`,
      ].join('\n'),
    };
  }
}
