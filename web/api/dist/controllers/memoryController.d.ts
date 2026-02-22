/**
 * Memory Controller
 *
 * Handles business logic for memory/vault operations.
 */
interface MemoryEntry {
    path: string;
    content: string;
    metadata: Record<string, any>;
    createdAt: string;
    updatedAt: string;
}
interface SearchResult {
    path: string;
    matches: string[];
    score: number;
}
interface ContextData {
    recentFiles: string[];
    activeTopics: string[];
    sessionContext: Record<string, any>;
}
export declare class MemoryController {
    private vaultPath;
    constructor();
    /**
     * Read a file from the vault
     */
    readFile(filePath: string): Promise<MemoryEntry | null>;
    /**
     * Write content to the vault
     */
    writeFile(filePath: string, content: string, metadata?: Record<string, any>): Promise<MemoryEntry>;
    /**
     * Delete a file from the vault
     */
    deleteFile(filePath: string): Promise<boolean>;
    /**
     * Search the vault
     */
    search(query: string, options?: {
        path?: string;
        tags?: string[];
        limit?: number;
    }): Promise<SearchResult[]>;
    /**
     * List files in a directory
     */
    listFiles(dirPath?: string): Promise<string[]>;
    /**
     * Get current context
     */
    getContext(): Promise<ContextData>;
    /**
     * Update context
     */
    updateContextData(key: string, value: any): Promise<ContextData>;
    /**
     * Clear context
     */
    clearContext(): Promise<void>;
    /**
     * Get vault statistics
     */
    getStats(): Promise<Record<string, any>>;
    private extractMetadata;
    private updateContext;
}
export {};
//# sourceMappingURL=memoryController.d.ts.map