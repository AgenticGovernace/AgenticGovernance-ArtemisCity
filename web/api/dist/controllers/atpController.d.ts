/**
 * ATP Controller
 *
 * Handles business logic for Artemis Transmission Protocol operations.
 */
type ATPMode = 'RESEARCH' | 'EXECUTE' | 'REPORT' | 'DELEGATE' | 'QUERY';
type ATPPriority = 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW' | 'BACKGROUND';
type ATPActionType = 'CREATE' | 'READ' | 'UPDATE' | 'DELETE' | 'SEARCH' | 'ANALYZE' | 'SYNC' | 'NOTIFY';
interface ATPHeader {
    mode: ATPMode;
    context: string;
    priority: ATPPriority;
    actionType: ATPActionType;
    targetZone: string;
    specialNotes?: string;
    timestamp: string;
    messageId: string;
    senderId: string;
    receiverId?: string;
}
interface ATPMessage {
    header: ATPHeader;
    payload: any;
    metadata?: Record<string, any>;
}
interface ATPResponse {
    success: boolean;
    messageId: string;
    response?: any;
    error?: string;
    processingTime?: number;
}
export declare class ATPController {
    /**
     * Send an ATP message
     */
    sendMessage(message: Partial<ATPMessage>): Promise<ATPResponse>;
    /**
     * Route a message to appropriate handler
     */
    routeMessage(message: ATPMessage): Promise<any>;
    /**
     * Validate an ATP message
     */
    validateMessage(message: Partial<ATPMessage>): {
        valid: boolean;
        error?: string;
        warnings?: string[];
    };
    /**
     * Format a message for display
     */
    formatMessage(message: ATPMessage): string;
    /**
     * Get available modes
     */
    getModes(): {
        name: ATPMode;
        description: string;
    }[];
    /**
     * Get available priorities
     */
    getPriorities(): {
        name: ATPPriority;
        description: string;
        color: string;
    }[];
    /**
     * Get available action types
     */
    getActionTypes(): {
        name: ATPActionType;
        description: string;
    }[];
    /**
     * Get message by ID
     */
    getMessage(messageId: string): ATPMessage | null;
    /**
     * Get response by message ID
     */
    getResponse(messageId: string): ATPResponse | null;
    /**
     * Get message queue status
     */
    getQueueStatus(): {
        pending: number;
        recent: ATPMessage[];
    };
    private generateMessageId;
    private determineDestination;
}
export {};
//# sourceMappingURL=atpController.d.ts.map