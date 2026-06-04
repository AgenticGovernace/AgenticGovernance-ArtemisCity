import { deleteNote as deleteObsidianNote } from '../../services/obsidianRestAPI/methods';
import { wrapTool } from './wrapTool';

/**
 * Delete a note from the Obsidian vault.
 *
 * @param path - Vault-relative note path to delete.
 * @returns Wrapped tool result containing the deletion status message.
 */
export const deleteNote = wrapTool('deleteNote', async (path: string) => {
  await deleteObsidianNote(path);
  return { message: `Note '${path}' deleted successfully.` };
});
