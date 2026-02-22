"use strict";
/**
 * Agent Controller
 *
 * Handles business logic for agent management operations.
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.AgentController = void 0;
// In-memory store (would be replaced with database in production)
const store = {
    agents: new Map()
};
// Initialize with default agents
const defaultAgents = [
    {
        id: 'artemis',
        name: 'Artemis',
        role: 'Mayor / Orchestrator',
        status: 'active',
        trustLevel: 0.95,
        capabilities: ['orchestrate', 'delegate', 'monitor', 'report'],
        zones: ['all'],
        metadata: {
            description: 'Central orchestrator and task coordinator',
            emoji: '🏛️'
        },
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString()
    },
    {
        id: 'packrat',
        name: 'PackRat',
        role: 'Postmaster / Memory Manager',
        status: 'active',
        trustLevel: 0.85,
        capabilities: ['read', 'write', 'search', 'organize', 'archive'],
        zones: ['vault', 'memory'],
        metadata: {
            description: 'Manages vault operations and memory persistence',
            emoji: '📦'
        },
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString()
    },
    {
        id: 'copilot',
        name: 'Copilot',
        role: 'Assistant / User Interface',
        status: 'active',
        trustLevel: 0.80,
        capabilities: ['assist', 'query', 'suggest', 'format'],
        zones: ['user', 'interface'],
        metadata: {
            description: 'User-facing assistant and query handler',
            emoji: '🤖'
        },
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString()
    },
    {
        id: 'daemon',
        name: 'Daemon',
        role: 'City Manager / Background Services',
        status: 'active',
        trustLevel: 0.85,
        capabilities: ['schedule', 'maintain', 'backup', 'optimize'],
        zones: ['system', 'background'],
        metadata: {
            description: 'Handles background tasks and system maintenance',
            emoji: '⚙️'
        },
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString()
    }
];
// Initialize store with default agents
defaultAgents.forEach(agent => store.agents.set(agent.id, agent));
class AgentController {
    /**
     * Get all registered agents
     */
    async getAllAgents() {
        return Array.from(store.agents.values());
    }
    /**
     * Get a specific agent by ID
     */
    async getAgent(id) {
        return store.agents.get(id) || null;
    }
    /**
     * Register a new agent
     */
    async registerAgent(agentData) {
        const id = agentData.id || this.generateId(agentData.name || 'agent');
        const agent = {
            id,
            name: agentData.name || id,
            role: agentData.role || 'Citizen',
            status: 'active',
            trustLevel: agentData.trustLevel ?? 0.5,
            capabilities: agentData.capabilities || [],
            zones: agentData.zones || [],
            metadata: agentData.metadata || {},
            createdAt: new Date().toISOString(),
            updatedAt: new Date().toISOString()
        };
        store.agents.set(id, agent);
        return agent;
    }
    /**
     * Update an existing agent
     */
    async updateAgent(id, updates) {
        const existing = store.agents.get(id);
        if (!existing)
            return null;
        const updated = {
            ...existing,
            ...updates,
            id, // Prevent ID change
            updatedAt: new Date().toISOString()
        };
        store.agents.set(id, updated);
        return updated;
    }
    /**
     * Delete an agent
     */
    async deleteAgent(id) {
        return store.agents.delete(id);
    }
    /**
     * Suspend an agent
     */
    async suspendAgent(id, reason) {
        const agent = store.agents.get(id);
        if (!agent)
            return null;
        agent.status = 'suspended';
        agent.metadata.suspendedAt = new Date().toISOString();
        agent.metadata.suspendReason = reason;
        agent.updatedAt = new Date().toISOString();
        store.agents.set(id, agent);
        return agent;
    }
    /**
     * Activate an agent
     */
    async activateAgent(id) {
        const agent = store.agents.get(id);
        if (!agent)
            return null;
        agent.status = 'active';
        delete agent.metadata.suspendedAt;
        delete agent.metadata.suspendReason;
        agent.updatedAt = new Date().toISOString();
        store.agents.set(id, agent);
        return agent;
    }
    /**
     * Get agent's card (formatted for display)
     */
    async getAgentCard(id) {
        const agent = store.agents.get(id);
        if (!agent)
            return null;
        return {
            ...agent,
            trustBadge: this.getTrustBadge(agent.trustLevel),
            statusEmoji: this.getStatusEmoji(agent.status),
            formattedCapabilities: agent.capabilities.join(', '),
            formattedZones: agent.zones.join(', ')
        };
    }
    /**
     * Get agents by zone
     */
    async getAgentsByZone(zone) {
        return Array.from(store.agents.values()).filter(agent => agent.zones.includes(zone) || agent.zones.includes('all'));
    }
    /**
     * Get agents by capability
     */
    async getAgentsByCapability(capability) {
        return Array.from(store.agents.values()).filter(agent => agent.capabilities.includes(capability));
    }
    /**
     * Get agents by status
     */
    async getAgentsByStatus(status) {
        return Array.from(store.agents.values()).filter(agent => agent.status === status);
    }
    // Helper methods
    generateId(name) {
        return name.toLowerCase().replace(/\s+/g, '-') + '-' + Date.now().toString(36);
    }
    getTrustBadge(level) {
        if (level >= 0.9)
            return '🏆 FULL';
        if (level >= 0.7)
            return '⭐ HIGH';
        if (level >= 0.5)
            return '✓ MEDIUM';
        if (level >= 0.3)
            return '⚠️ LOW';
        return '🚫 UNTRUSTED';
    }
    getStatusEmoji(status) {
        switch (status) {
            case 'active': return '🟢';
            case 'suspended': return '🟡';
            case 'inactive': return '🔴';
            default: return '⚪';
        }
    }
}
exports.AgentController = AgentController;
//# sourceMappingURL=agentController.js.map