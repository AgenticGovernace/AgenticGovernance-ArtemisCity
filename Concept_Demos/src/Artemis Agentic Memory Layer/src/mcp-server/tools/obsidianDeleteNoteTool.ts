import { deleteNote as deleteObsidianNote } from '../../services/obsidianRestAPI/methods';
import { wrapTool } from './wrapTool';

export const deleteNote = wrapTool('deleteNote', async (path: string) => {
  await deleteObsidianNote(path);
  return { message: `Note '${path}' deleted successfully.` };
});
