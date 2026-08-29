import { searchReplace as obsidianSearchReplace } from "../../services/obsidianRestAPI/methods";
import { wrapTool } from "./wrapTool";

/**
 * Replace matching text inside a note and return the updated content.
 *
 * @param path - Vault-relative note path to update.
 * @param search - Literal text to find inside the note.
 * @param replace - Replacement text to write in place of each match.
 * @returns Wrapped tool result containing the updated note content and status message.
 */
export const searchReplace = wrapTool(
  "searchReplace",
  async (path: string, search: string, replace: string) => {
    const content = await obsidianSearchReplace(path, search, replace);
    return {
      data: { path, content },
      message: `Search and replace in '${path}' successful.`,
    };
  },
);
