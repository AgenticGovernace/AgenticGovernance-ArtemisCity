/**
 * API Utility Helpers
 *
 * Common utility functions for the API.
 */
/**
 * Paginate an array
 */
export declare const paginate: <T>(items: T[], page?: number, limit?: number) => {
    data: T[];
    pagination: PaginationInfo;
};
interface PaginationInfo {
    currentPage: number;
    totalPages: number;
    totalItems: number;
    itemsPerPage: number;
    hasNextPage: boolean;
    hasPrevPage: boolean;
}
/**
 * Deep merge objects
 */
export declare const deepMerge: <T extends Record<string, any>>(target: T, source: Partial<T>) => T;
/**
 * Pick specific keys from an object
 */
export declare const pick: <T extends Record<string, any>, K extends keyof T>(obj: T, keys: K[]) => Pick<T, K>;
/**
 * Omit specific keys from an object
 */
export declare const omit: <T extends Record<string, any>, K extends keyof T>(obj: T, keys: K[]) => Omit<T, K>;
/**
 * Debounce function
 */
export declare const debounce: <T extends (...args: any[]) => any>(fn: T, delay: number) => ((...args: Parameters<T>) => void);
/**
 * Throttle function
 */
export declare const throttle: <T extends (...args: any[]) => any>(fn: T, limit: number) => ((...args: Parameters<T>) => void);
/**
 * Sleep/delay function
 */
export declare const sleep: (ms: number) => Promise<void>;
/**
 * Retry function with exponential backoff
 */
export declare const retry: <T>(fn: () => Promise<T>, options?: {
    maxAttempts?: number;
    delay?: number;
    backoff?: number;
}) => Promise<T>;
/**
 * Generate a unique ID
 */
export declare const generateId: (prefix?: string) => string;
/**
 * Format date to ISO string
 */
export declare const formatDate: (date: Date | string | number) => string;
/**
 * Parse query string parameters
 */
export declare const parseQueryParams: (query: Record<string, any>) => Record<string, any>;
/**
 * Sanitize string for safe use
 */
export declare const sanitize: (str: string) => string;
/**
 * Validate email format
 */
export declare const isValidEmail: (email: string) => boolean;
/**
 * Validate URL format
 */
export declare const isValidUrl: (url: string) => boolean;
/**
 * Clamp a number between min and max
 */
export declare const clamp: (num: number, min: number, max: number) => number;
/**
 * Check if object is empty
 */
export declare const isEmpty: (obj: any) => boolean;
/**
 * Create response envelope
 */
export declare const createResponse: <T>(data: T, options?: {
    message?: string;
    meta?: Record<string, any>;
}) => {
    success: true;
    data: T;
    message?: string;
    meta?: Record<string, any>;
};
/**
 * Hash a string (simple non-crypto hash for IDs)
 */
export declare const simpleHash: (str: string) => string;
export {};
//# sourceMappingURL=helpers.d.ts.map