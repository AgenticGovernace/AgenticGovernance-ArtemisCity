import { logger } from '../../utils/logger';

export type ToolSuccess = { success: true; data?: unknown; message?: string };
export type ToolFailure = { success: false; error: string };
export type ToolResult = ToolSuccess | ToolFailure;

export function wrapTool<Args extends unknown[]>(
  name: string,
  fn: (...args: Args) => Promise<Omit<ToolSuccess, 'success'>>,
): (...args: Args) => Promise<ToolResult> {
  return async (...args: Args) => {
    try {
      logger.debug(`${name} called`, ...args);
      const payload = await fn(...args);
      logger.info(`${name} succeeded`);
      return { success: true, ...payload };
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      logger.error(`${name} failed: ${message}`);
      return { success: false, error: message };
    }
  };
}
