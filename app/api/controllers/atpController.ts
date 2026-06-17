/**
 * ATP Controller
 *
 * Delegates Artemis Transmission Protocol parsing and validation to the
 * canonical Python ATP models.
 */

import { callBridge } from '../lib/pythonBridge';

export class ATPController {
  async parseMessage(message: string): Promise<unknown> {
    return callBridge('atp.parse', { message });
  }

  async validateMessage(message: string, strict = false): Promise<unknown> {
    return callBridge('atp.validate', { message, strict });
  }

  async sendMessage(message: unknown): Promise<unknown> {
    return callBridge('atp.send', normalizeMessagePayload(message));
  }

  async routeMessage(message: unknown): Promise<unknown> {
    return callBridge('atp.route', normalizeMessagePayload(message));
  }

  async getModes(): Promise<unknown> {
    return callBridge('atp.modes');
  }

  async getPriorities(): Promise<unknown> {
    return callBridge('atp.priorities');
  }

  async getActionTypes(): Promise<unknown> {
    return callBridge('atp.action_types');
  }

  async getTemplate(): Promise<unknown> {
    return callBridge('atp.template');
  }

  async formatMessage(message: unknown): Promise<unknown> {
    return callBridge('atp.format', normalizeMessagePayload(message));
  }

  async getMessage(messageId: string): Promise<unknown> {
    return callBridge('atp.get_message', { message_id: messageId });
  }

  async getResponse(messageId: string): Promise<unknown> {
    return callBridge('atp.get_response', { message_id: messageId });
  }

  async getQueueStatus(): Promise<unknown> {
    return callBridge('atp.queue');
  }
}

function normalizeMessagePayload(message: unknown): Record<string, unknown> {
  if (typeof message === 'string') {
    return { message };
  }
  if (message && typeof message === 'object' && !Array.isArray(message)) {
    return message as Record<string, unknown>;
  }
  return { message: String(message ?? '') };
}
