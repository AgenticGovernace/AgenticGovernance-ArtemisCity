/**
 * Agent Controller
 *
 * Handles business logic for agent management operations.
 */
interface AgentCard {
    id: string;
    name: string;
    role: string;
    status: 'active' | 'suspended' | 'inactive';
    trustLevel: number;
    capabilities: string[];
    zones: string[];
    metadata: Record<string, any>;
    createdAt: string;
    updatedAt: string;
}
export declare class AgentController {
    /**
     * Get all registered agents
     */
    getAllAgents(): Promise<AgentCard[]>;
    /**
     * Get a specific agent by ID
     */
    getAgent(id: string): Promise<AgentCard | null>;
    /**
     * Register a new agent
     */
    registerAgent(agentData: Partial<AgentCard>): Promise<AgentCard>;
    /**
     * Update an existing agent
     */
    updateAgent(id: string, updates: Partial<AgentCard>): Promise<AgentCard | null>;
    /**
     * Delete an agent
     */
    deleteAgent(id: string): Promise<boolean>;
    /**
     * Suspend an agent
     */
    suspendAgent(id: string, reason?: string): Promise<AgentCard | null>;
    /**
     * Activate an agent
     */
    activateAgent(id: string): Promise<AgentCard | null>;
    /**
     * Get agent's card (formatted for display)
     */
    getAgentCard(id: string): Promise<Record<string, any> | null>;
    /**
     * Get agents by zone
     */
    getAgentsByZone(zone: string): Promise<AgentCard[]>;
    /**
     * Get agents by capability
     */
    getAgentsByCapability(capability: string): Promise<AgentCard[]>;
    /**
     * Get agents by status
     */
    getAgentsByStatus(status: string): Promise<AgentCard[]>;
    private generateId;
    private getTrustBadge;
    private getStatusEmoji;
}
export {};
//# sourceMappingURL=agentController.d.ts.map