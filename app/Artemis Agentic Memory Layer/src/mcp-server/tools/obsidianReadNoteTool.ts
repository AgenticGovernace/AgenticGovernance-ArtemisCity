import { readNote as readObsidianNote } from "../../services/obsidianRestAPI/methods";
import { wrapTool } from "./wrapTool";

/**
 * Read the markdown content of a note from the Obsidian vault.
 *
 * @param path - Vault-relative note path to read.
 * @returns Wrapped tool result containing the note path and markdown content.
 */
export const getContext = wrapTool("getContext", async (path: string) => {
  const content = await readObsidianNote(path);
  return { data: { path, content } };
});
