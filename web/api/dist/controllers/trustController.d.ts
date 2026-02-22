/**
 * Trust Controller
 *
 * Handles business logic for trust management and Hebbian learning.
 */
type TrustLevel = 'FULL' | 'HIGH' | 'MEDIUM' | 'LOW' | 'UNTRUSTED';
interface TrustScore {
    entityId: string;
    entityType: 'agent' | 'user' | 'service' | 'external';
    score: number;
    level: TrustLevel;
    successCount: number;
    failureCount: number;
    lastInteraction: string;
    createdAt: string;
    updatedAt: string;
}
interface HebbianWeight {
    agent1: string;
    agent2: string;
    weight: number;
    interactions: number;
    lastUpdated: string;
}
interface TrustReport {
    totalEntities: number;
    byLevel: Record<TrustLevel, number>;
    byType: Record<string, number>;
    averageScore: number;
    recentChanges: TrustScore[];
    hebbianConnections: number;
}
export declare class TrustController {
    /**
     * Get trust score for an entity
     */
    getTrustScore(entityId: string): Promise<TrustScore | null>;
    /**
     * Set trust score for an entity
     */
    setTrustScore(entityId: string, score: number, entityType?: string): Promise<TrustScore>;
    /**
     * Record a successful operation
     */
    recordSuccess(entityId: string, amount?: number): Promise<number | null>;
    /**
     * Record a failed operation
     */
    recordFailure(entityId: string, amount?: number): Promise<number | null>;
    /**
     * Get permissions for an entity
     */
    getPermissions(entityId: string): Promise<{
        entityId: string;
        level: TrustLevel;
        operations: string[];
    }>;
    /**
     * Check if entity can perform operation
     */
    canPerformOperation(entityId: string, operation: string): Promise<boolean>;
    /**
     * Get Hebbian weights
     */
    getHebbianWeights(): Promise<HebbianWeight[]>;
    /**
     * Update Hebbian weight between two agents
     */
    updateHebbianWeight(agent1: string, agent2: string, delta: number): Promise<number>;
    /**
     * Get comprehensive trust report
     */
    getTrustReport(): Promise<TrustReport>;
    /**
     * Apply trust decay (called periodically)
     */
    applyDecay(decayRate?: number): Promise<number>;
    /**
     * Get trust level definitions
     */
    getTrustLevels(): {
        name: TrustLevel;
        minScore: number;
        operations: string[];
    }[];
    private scoreToLevel;
}
export {};
//# sourceMappingURL=trustController.d.ts.map