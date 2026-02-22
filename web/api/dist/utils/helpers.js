"use strict";
/**
 * API Utility Helpers
 *
 * Common utility functions for the API.
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.simpleHash = exports.createResponse = exports.isEmpty = exports.clamp = exports.isValidUrl = exports.isValidEmail = exports.sanitize = exports.parseQueryParams = exports.formatDate = exports.generateId = exports.retry = exports.sleep = exports.throttle = exports.debounce = exports.omit = exports.pick = exports.deepMerge = exports.paginate = void 0;
/**
 * Paginate an array
 */
const paginate = (items, page = 1, limit = 10) => {
    const totalItems = items.length;
    const totalPages = Math.ceil(totalItems / limit);
    const currentPage = Math.max(1, Math.min(page, totalPages || 1));
    const startIndex = (currentPage - 1) * limit;
    const endIndex = startIndex + limit;
    return {
        data: items.slice(startIndex, endIndex),
        pagination: {
            currentPage,
            totalPages,
            totalItems,
            itemsPerPage: limit,
            hasNextPage: currentPage < totalPages,
            hasPrevPage: currentPage > 1
        }
    };
};
exports.paginate = paginate;
/**
 * Deep merge objects
 */
const deepMerge = (target, source) => {
    const output = { ...target };
    for (const key in source) {
        if (source[key] && typeof source[key] === 'object' && !Array.isArray(source[key])) {
            output[key] = (0, exports.deepMerge)(output[key] || {}, source[key]);
        }
        else {
            output[key] = source[key];
        }
    }
    return output;
};
exports.deepMerge = deepMerge;
/**
 * Pick specific keys from an object
 */
const pick = (obj, keys) => {
    const result = {};
    for (const key of keys) {
        if (key in obj) {
            result[key] = obj[key];
        }
    }
    return result;
};
exports.pick = pick;
/**
 * Omit specific keys from an object
 */
const omit = (obj, keys) => {
    const result = { ...obj };
    for (const key of keys) {
        delete result[key];
    }
    return result;
};
exports.omit = omit;
/**
 * Debounce function
 */
const debounce = (fn, delay) => {
    let timeoutId;
    return (...args) => {
        clearTimeout(timeoutId);
        timeoutId = setTimeout(() => fn(...args), delay);
    };
};
exports.debounce = debounce;
/**
 * Throttle function
 */
const throttle = (fn, limit) => {
    let inThrottle = false;
    return (...args) => {
        if (!inThrottle) {
            fn(...args);
            inThrottle = true;
            setTimeout(() => (inThrottle = false), limit);
        }
    };
};
exports.throttle = throttle;
/**
 * Sleep/delay function
 */
const sleep = (ms) => {
    return new Promise(resolve => setTimeout(resolve, ms));
};
exports.sleep = sleep;
/**
 * Retry function with exponential backoff
 */
const retry = async (fn, options = {}) => {
    const { maxAttempts = 3, delay = 1000, backoff = 2 } = options;
    let lastError;
    for (let attempt = 1; attempt <= maxAttempts; attempt++) {
        try {
            return await fn();
        }
        catch (error) {
            lastError = error;
            if (attempt < maxAttempts) {
                const waitTime = delay * Math.pow(backoff, attempt - 1);
                await (0, exports.sleep)(waitTime);
            }
        }
    }
    throw lastError;
};
exports.retry = retry;
/**
 * Generate a unique ID
 */
const generateId = (prefix = '') => {
    const timestamp = Date.now().toString(36);
    const random = Math.random().toString(36).slice(2, 8);
    return prefix ? `${prefix}-${timestamp}-${random}` : `${timestamp}-${random}`;
};
exports.generateId = generateId;
/**
 * Format date to ISO string
 */
const formatDate = (date) => {
    return new Date(date).toISOString();
};
exports.formatDate = formatDate;
/**
 * Parse query string parameters
 */
const parseQueryParams = (query) => {
    const parsed = {};
    for (const [key, value] of Object.entries(query)) {
        if (value === 'true') {
            parsed[key] = true;
        }
        else if (value === 'false') {
            parsed[key] = false;
        }
        else if (!isNaN(Number(value)) && value !== '') {
            parsed[key] = Number(value);
        }
        else {
            parsed[key] = value;
        }
    }
    return parsed;
};
exports.parseQueryParams = parseQueryParams;
/**
 * Sanitize string for safe use
 */
const sanitize = (str) => {
    return str
        .replace(/[<>]/g, '')
        .replace(/javascript:/gi, '')
        .replace(/data:/gi, '')
        .replace(/vbscript:/gi, '')
        .trim();
};
exports.sanitize = sanitize;
/**
 * Validate email format
 */
const isValidEmail = (email) => {
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return emailRegex.test(email);
};
exports.isValidEmail = isValidEmail;
/**
 * Validate URL format
 */
const isValidUrl = (url) => {
    try {
        new URL(url);
        return true;
    }
    catch {
        return false;
    }
};
exports.isValidUrl = isValidUrl;
/**
 * Clamp a number between min and max
 */
const clamp = (num, min, max) => {
    return Math.min(Math.max(num, min), max);
};
exports.clamp = clamp;
/**
 * Check if object is empty
 */
const isEmpty = (obj) => {
    if (obj === null || obj === undefined)
        return true;
    if (Array.isArray(obj))
        return obj.length === 0;
    if (typeof obj === 'object')
        return Object.keys(obj).length === 0;
    if (typeof obj === 'string')
        return obj.trim().length === 0;
    return false;
};
exports.isEmpty = isEmpty;
/**
 * Create response envelope
 */
const createResponse = (data, options = {}) => {
    return {
        success: true,
        data,
        ...(options.message && { message: options.message }),
        ...(options.meta && { meta: options.meta })
    };
};
exports.createResponse = createResponse;
/**
 * Hash a string (simple non-crypto hash for IDs)
 */
const simpleHash = (str) => {
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
        const char = str.charCodeAt(i);
        hash = ((hash << 5) - hash) + char;
        hash = hash & hash;
    }
    return Math.abs(hash).toString(36);
};
exports.simpleHash = simpleHash;
//# sourceMappingURL=helpers.js.map