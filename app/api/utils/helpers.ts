/**
 * API Utility Helpers
 *
 * Common utility functions for the API.
 */

/**
 * Paginate an array of items.
 *
 * @param items - Source items to paginate.
 * @param page - One-based page number to return.
 * @param limit - Maximum number of items to include on the page.
 * @returns Slice of items plus pagination metadata for the current page.
 */
export const paginate = <T>(
  items: T[],
  page: number = 1,
  limit: number = 10,
): { data: T[]; pagination: PaginationInfo } => {
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
      hasPrevPage: currentPage > 1,
    },
  };
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
 * Deeply merge two objects.
 *
 * @param target - Base object that receives merged fields.
 * @param source - Partial object whose fields should override the target.
 * @returns Deeply merged object with nested plain-object fields combined recursively.
 */
export const deepMerge = <T extends Record<string, any>>(
  target: T,
  source: Partial<T>,
): T => {
  const output: Record<string, any> = { ...target };

  for (const key in source) {
    if (
      source[key] &&
      typeof source[key] === "object" &&
      !Array.isArray(source[key])
    ) {
      output[key] = deepMerge(output[key] || {}, source[key] as any);
    } else {
      output[key] = source[key];
    }
  }

  return output as T;
};

/**
 * Pick specific keys from an object.
 *
 * @param obj - Source object to read from.
 * @param keys - Keys to copy into the new object.
 * @returns New object containing only the requested keys.
 */
export const pick = <T extends Record<string, any>, K extends keyof T>(
  obj: T,
  keys: K[],
): Pick<T, K> => {
  const result = {} as Pick<T, K>;
  for (const key of keys) {
    if (key in obj) {
      result[key] = obj[key];
    }
  }
  return result;
};

/**
 * Omit specific keys from an object.
 *
 * @param obj - Source object to clone.
 * @param keys - Keys to remove from the cloned object.
 * @returns New object without the omitted keys.
 */
export const omit = <T extends Record<string, any>, K extends keyof T>(
  obj: T,
  keys: K[],
): Omit<T, K> => {
  const result = { ...obj };
  for (const key of keys) {
    delete result[key];
  }
  return result as Omit<T, K>;
};

/**
 * Debounce a function call.
 *
 * @param fn - Function to invoke after the quiet period elapses.
 * @param delay - Quiet period, in milliseconds, before the function runs.
 * @returns Debounced wrapper that resets its timer whenever it is called again.
 */
export const debounce = <T extends (...args: any[]) => any>(
  fn: T,
  delay: number,
): ((...args: Parameters<T>) => void) => {
  let timeoutId: NodeJS.Timeout;

  return (...args: Parameters<T>) => {
    clearTimeout(timeoutId);
    timeoutId = setTimeout(() => fn(...args), delay);
  };
};

/**
 * Throttle a function call.
 *
 * @param fn - Function to invoke at most once per throttle window.
 * @param limit - Window size, in milliseconds, between allowed invocations.
 * @returns Throttled wrapper that drops calls made during the active window.
 */
export const throttle = <T extends (...args: any[]) => any>(
  fn: T,
  limit: number,
): ((...args: Parameters<T>) => void) => {
  let inThrottle = false;

  return (...args: Parameters<T>) => {
    if (!inThrottle) {
      fn(...args);
      inThrottle = true;
      setTimeout(() => (inThrottle = false), limit);
    }
  };
};

/**
 * Sleep for a fixed amount of time.
 *
 * @param ms - Delay duration in milliseconds.
 * @returns Promise that resolves after the delay elapses.
 */
export const sleep = (ms: number): Promise<void> => {
  return new Promise((resolve) => setTimeout(resolve, ms));
};

/**
 * Retry an asynchronous function with exponential backoff.
 *
 * @param fn - Asynchronous operation to retry.
 * @param options - Retry settings such as maximum attempts, initial delay, and backoff multiplier.
 * @returns Promise resolving to the first successful result returned by `fn`.
 */
export const retry = async <T>(
  fn: () => Promise<T>,
  options: { maxAttempts?: number; delay?: number; backoff?: number } = {},
): Promise<T> => {
  const { maxAttempts = 3, delay = 1000, backoff = 2 } = options;

  let lastError: Error | undefined;

  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    try {
      return await fn();
    } catch (error) {
      lastError = error as Error;

      if (attempt < maxAttempts) {
        const waitTime = delay * Math.pow(backoff, attempt - 1);
        await sleep(waitTime);
      }
    }
  }

  throw lastError;
};

/**
 * Generate a unique identifier string.
 *
 * @param prefix - Optional prefix to prepend to the generated identifier.
 * @returns Generated identifier string.
 */
export const generateId = (prefix: string = ""): string => {
  const timestamp = Date.now().toString(36);
  const random = Math.random().toString(36).slice(2, 8);
  return prefix ? `${prefix}-${timestamp}-${random}` : `${timestamp}-${random}`;
};

/**
 * Format a date-like value as an ISO timestamp.
 *
 * @param date - Date-like value to format.
 * @returns ISO 8601 timestamp string.
 */
export const formatDate = (date: Date | string | number): string => {
  return new Date(date).toISOString();
};

/**
 * Parse raw query-string values into booleans and numbers when possible.
 *
 * @param query - Raw query parameter map.
 * @returns New object with primitive values normalized for downstream use.
 */
export const parseQueryParams = (
  query: Record<string, any>,
): Record<string, any> => {
  const parsed: Record<string, any> = {};

  for (const [key, value] of Object.entries(query)) {
    if (value === "true") {
      parsed[key] = true;
    } else if (value === "false") {
      parsed[key] = false;
    } else if (!isNaN(Number(value)) && value !== "") {
      parsed[key] = Number(value);
    } else {
      parsed[key] = value;
    }
  }

  return parsed;
};

/**
 * Sanitize a string for safe display or logging.
 *
 * @param str - String to sanitize.
 * @returns Sanitized string with unsafe protocol prefixes and angle brackets removed.
 */
export const sanitize = (str: string): string => {
  return str
    .replace(/[<>]/g, "")
    .replace(/javascript:/gi, "")
    .replace(/data:/gi, "")
    .replace(/vbscript:/gi, "")
    .trim();
};

/**
 * Validate basic email address formatting.
 *
 * @param email - Email address to validate.
 * @returns Whether the email matches a basic address pattern.
 */
export const isValidEmail = (email: string): boolean => {
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  return emailRegex.test(email);
};

/**
 * Validate whether a string can be parsed as a URL.
 *
 * @param url - URL string to validate.
 * @returns Whether the string can be parsed as a valid URL.
 */
export const isValidUrl = (url: string): boolean => {
  try {
    new URL(url);
    return true;
  } catch {
    return false;
  }
};

/**
 * Clamp a number between a minimum and maximum.
 *
 * @param num - Number to clamp.
 * @param min - Lower bound allowed for the number.
 * @param max - Upper bound allowed for the number.
 * @returns Number constrained to the inclusive `min`/`max` range.
 */
export const clamp = (num: number, min: number, max: number): number => {
  return Math.min(Math.max(num, min), max);
};

/**
 * Check whether a value should be treated as empty.
 *
 * @param obj - Value to inspect.
 * @returns Whether the supplied value is nullish, blank, or contains no items/keys.
 */
export const isEmpty = (obj: any): boolean => {
  if (obj === null || obj === undefined) return true;
  if (Array.isArray(obj)) return obj.length === 0;
  if (typeof obj === "object") return Object.keys(obj).length === 0;
  if (typeof obj === "string") return obj.trim().length === 0;
  return false;
};

/**
 * Create a standard success response envelope.
 *
 * @param data - Payload to include in the response body.
 * @param options - Optional response message and metadata.
 * @returns Success envelope containing the payload and any optional extras.
 */
export const createResponse = <T>(
  data: T,
  options: { message?: string; meta?: Record<string, any> } = {},
): { success: true; data: T; message?: string; meta?: Record<string, any> } => {
  return {
    success: true,
    data,
    ...(options.message && { message: options.message }),
    ...(options.meta && { meta: options.meta }),
  };
};

/**
 * Hash a string with a deterministic non-cryptographic algorithm.
 *
 * @param str - String to hash.
 * @returns Base-36 hash string derived from the input text.
 */
export const simpleHash = (str: string): string => {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    const char = str.charCodeAt(i);
    hash = (hash << 5) - hash + char;
    hash = hash & hash;
  }
  return Math.abs(hash).toString(36);
};
