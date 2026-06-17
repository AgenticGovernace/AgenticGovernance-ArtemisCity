/**
 * Memory Controller
 *
 * Vault and memory-bus operations delegated to the Python bridge.
 */

import { callBridge } from '../lib/pythonBridge';

export interface SearchOptions {
  path?: string;
  tags?: string[];
  limit?: number;
}

export class MemoryController {
  async readFile(filePath: string): Promise<unknown> {
    return callBridge('memory.read', { path: filePath });
  }

  async writeFile(
    filePath: string,
    content: string,
    metadata?: Record<string, unknown>
  ): Promise<unknown> {
    return callBridge('memory.write', {
      path: filePath,
      content,
      metadata: metadata ?? undefined,
    });
  }

  async deleteFile(filePath: string): Promise<unknown> {
    return callBridge('memory.delete', { path: filePath });
  }

  async search(query: string, options: SearchOptions = {}): Promise<unknown> {
    return callBridge('memory.search', {
      query,
      path: options.path ?? '',
      limit: options.limit ?? 10,
      tags: options.tags,
    });
  }

  async listFiles(dirPath: string = ''): Promise<unknown> {
    return callBridge('memory.list', { path: dirPath });
  }

  async getContext(): Promise<unknown> {
    return callBridge('memory.stats');
  }

  async updateContextData(key: string, value: unknown): Promise<unknown> {
    return callBridge('memory.write', {
      path: `.artemis/context/${key}.json`,
      content: JSON.stringify(value, null, 2),
      metadata: { kind: 'context', key },
    });
  }

  async clearContext(): Promise<unknown> {
    return callBridge('memory.delete', { path: '.artemis/context.json' });
  }

  async getStats(): Promise<unknown> {
    return callBridge('memory.stats');
  }
}
