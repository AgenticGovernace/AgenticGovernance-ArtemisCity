import { readNote as readObsidianNote } from '../../services/obsidianRestAPI/methods';
import { wrapTool } from './wrapTool';

export const getContext = wrapTool('getContext', async (path: string) => {
  const content = await readObsidianNote(path);
  return { data: { path, content } };
});
