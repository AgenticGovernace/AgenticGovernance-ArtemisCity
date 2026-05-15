import { listNotes as listObsidianNotes } from '../../services/obsidianRestAPI/methods';
import { wrapTool } from './wrapTool';

export const listNotes = wrapTool('listNotes', async () => {
  const notes = await listObsidianNotes();
  return { data: notes };
});
