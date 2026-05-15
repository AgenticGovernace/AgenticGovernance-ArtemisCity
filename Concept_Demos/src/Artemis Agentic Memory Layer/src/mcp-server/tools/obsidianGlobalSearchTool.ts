import { searchNotes as searchObsidianNotes } from '../../services/obsidianRestAPI/methods';
import { wrapTool } from './wrapTool';

export const searchNotes = wrapTool('searchNotes', async (query: string) => {
  const results = await searchObsidianNotes(query);
  return { data: results };
});
