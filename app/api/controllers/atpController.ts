/**
 * ATP Controller
 *
 * Delegates Artemis Transmission Protocol parsing and validation to the
 * canonical Python ATP models.
 */

import { callBridge } from "../lib/pythonBridge";

export class ATPController {
  async parseMessage(message: string): Promise<unknown> {
    return callBridge("atp.parse", { message });
  }

  async validateMessage(message: string, strict = false): Promise<unknown> {
    return callBridge("atp.validate", { message, strict });
  }

  async sendMessage(message: unknown): Promise<unknown> {
    return callBridge(
      "atp.send",
      normalizeMessagePayload(message, ATP_SEND_FIELDS),
    );
  }

  async routeMessage(message: unknown): Promise<unknown> {
    return callBridge(
      "atp.route",
      normalizeMessagePayload(message, ATP_ROUTE_FIELDS),
    );
  }

  async getModes(): Promise<unknown> {
    return callBridge("atp.modes");
  }

  async getPriorities(): Promise<unknown> {
    return callBridge("atp.priorities");
  }

  async getActionTypes(): Promise<unknown> {
    return callBridge("atp.action_types");
  }

  async getTemplate(): Promise<unknown> {
    return callBridge("atp.template");
  }

  async formatMessage(message: unknown): Promise<unknown> {
    return callBridge(
      "atp.format",
      normalizeMessagePayload(message, ATP_FORMAT_FIELDS),
    );
  }

  async getMessage(messageId: string): Promise<unknown> {
    return callBridge("atp.get_message", { message_id: messageId });
  }

  async getResponse(messageId: string): Promise<unknown> {
    return callBridge("atp.get_response", { message_id: messageId });
  }

  async getQueueStatus(): Promise<unknown> {
    return callBridge("atp.queue");
  }
}

const ATP_SEND_FIELDS = ["message", "text", "atpMessage", "strict"] as const;
const ATP_ROUTE_FIELDS = [
  ...ATP_SEND_FIELDS,
  "message_id",
  "id",
  "required_capability",
  "capability",
] as const;
const ATP_FORMAT_FIELDS = [
  "message",
  "mode",
  "context",
  "priority",
  "action_type",
  "actionType",
  "target_zone",
  "targetZone",
  "special_notes",
  "specialNotes",
  "content",
] as const;

function normalizeMessagePayload(
  message: unknown,
  allowedFields: readonly string[],
): Record<string, unknown> {
  if (typeof message === "string") {
    return { message };
  }
  if (message && typeof message === "object" && !Array.isArray(message)) {
    const payload = message as Record<string, unknown>;
    const sanitized: Record<string, unknown> = {};
    for (const key of allowedFields) {
      if (Object.prototype.hasOwnProperty.call(payload, key)) {
        sanitized[key] = payload[key];
      }
    }
    return sanitized;
  }
  return { message: String(message ?? "") };
}
