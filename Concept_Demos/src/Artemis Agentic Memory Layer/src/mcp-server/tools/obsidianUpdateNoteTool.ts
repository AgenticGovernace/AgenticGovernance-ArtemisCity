import { updateNote as updateObsidianNote } from '../../services/obsidianRestAPI/methods';
import { wrapTool } from './wrapTool';

export const appendContext = wrapTool('appendContext', async (path: string, content: string) => {
  await updateObsidianNote(path, content, { append: true });
  return { message: `Content appended to note '${path}'.` };
});

export const updateNote = wrapTool('updateNote', async (path: string, content: string) => {
  await updateObsidianNote(path, content, { append: false });
  return { message: `Note '${path}' updated.` };
});
