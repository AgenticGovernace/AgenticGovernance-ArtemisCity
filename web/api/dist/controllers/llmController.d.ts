/**
 * LLM Controller
 *
 * Handles interactions with LLM providers (Claude, OpenAI, local models).
 */
interface Message {
    role: 'system' | 'user' | 'assistant';
    content: string;
    name?: string;
}
interface ChatOptions {
    temperature?: number;
    maxTokens?: number;
    topP?: number;
    stopSequences?: string[];
    systemPrompt?: string;
}
interface ChatResponse {
    id: string;
    model: string;
    content: string;
    role: 'assistant';
    finishReason: string;
    usage: {
        promptTokens: number;
        completionTokens: number;
        totalTokens: number;
    };
    createdAt: string;
}
interface EmbeddingResponse {
    model: string;
    embedding: number[];
    dimensions: number;
    usage: {
        totalTokens: number;
    };
}
interface StreamChunk {
    id: string;
    delta: string;
    finishReason?: string;
}
interface ModelInfo {
    id: string;
    name: string;
    provider: string;
    contextWindow: number;
    maxOutputTokens: number;
    inputCostPer1k: number;
    outputCostPer1k: number;
    capabilities: string[];
}
interface ProviderConfig {
    name: string;
    enabled: boolean;
    apiKey?: string;
    baseUrl?: string;
    defaultModel?: string;
    options?: Record<string, any>;
}
interface UsageStats {
    totalRequests: number;
    totalTokens: number;
    promptTokens: number;
    completionTokens: number;
    estimatedCost: number;
    byModel: Record<string, {
        requests: number;
        tokens: number;
    }>;
    byDay: Record<string, {
        requests: number;
        tokens: number;
    }>;
}
export declare class LLMController {
    private defaultModel;
    /**
     * Send a chat completion request
     */
    chat(messages: Message[], model?: string, options?: ChatOptions): Promise<ChatResponse>;
    /**
     * Send a text completion request
     */
    complete(prompt: string, model?: string, options?: ChatOptions): Promise<ChatResponse>;
    /**
     * Generate embeddings
     */
    embed(text: string | string[], model?: string): Promise<EmbeddingResponse>;
    /**
     * Stream chat completion
     */
    streamChat(messages: Message[], model?: string, options?: ChatOptions, onChunk?: (chunk: StreamChunk) => void): Promise<void>;
    /**
     * List available models
     */
    listModels(): Promise<ModelInfo[]>;
    /**
     * Get configured providers
     */
    getProviders(): ProviderConfig[];
    /**
     * Configure a provider
     */
    configureProvider(providerName: string, config: Partial<ProviderConfig>): Promise<ProviderConfig>;
    /**
     * Process an ATP message through LLM
     */
    processATP(atpMessage: any, model?: string, agentId?: string): Promise<ChatResponse>;
    /**
     * Get usage statistics
     */
    getUsage(filters?: {
        startDate?: string;
        endDate?: string;
        provider?: string;
    }): Promise<UsageStats>;
    private simulateChat;
    private generateMockResponse;
    private buildATPSystemPrompt;
    private getTemperatureForMode;
    private getMaxTokensForActionType;
    private logUsage;
}
export {};
//# sourceMappingURL=llmController.d.ts.map