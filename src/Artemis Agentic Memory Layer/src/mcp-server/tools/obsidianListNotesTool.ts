import { listNotes as listObsidianNotes } from '../../services/obsidianRestAPI/methods';
import { wrapTool } from './wrapTool';

/**
 * List markdown notes that are available in the Obsidian vault.
 *
 * @returns Wrapped tool result containing the discovered note paths.
 */
export const listNotes = wrapTool('listNotes', async () => {
  const notes = await listObsidianNotes();
  return { data: notes };
});
