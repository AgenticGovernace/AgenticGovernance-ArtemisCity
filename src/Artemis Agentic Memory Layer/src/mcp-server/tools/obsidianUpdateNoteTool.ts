import { updateNote as updateObsidianNote } from "../../services/obsidianRestAPI/methods";
import { wrapTool } from "./wrapTool";
/**
 * Append markdown content to an existing note in the Obsidian vault.
 *
 * @param path - Vault-relative note path to append to.
 * @param content - Markdown content to append.
 * @returns Wrapped tool result containing the append status message.
 */
export const appendContext = wrapTool(
  "appendContext",
  async (path: string, content: string) => {
    await updateObsidianNote(path, content, { append: true });
    return { message: `Content appended to note '${path}'.` };
  },
);

/**
 * Overwrite a note with new markdown content in the Obsidian vault.
 *
 * @param path - Vault-relative note path to overwrite.
 * @param content - Markdown content to write.
 * @returns Wrapped tool result containing the update status message.
 */
export const updateNote = wrapTool(
  "updateNote",
  async (path: string, content: string) => {
    await updateObsidianNote(path, content, { append: false });
    return { message: `Note '${path}' updated.` };
  },
);
