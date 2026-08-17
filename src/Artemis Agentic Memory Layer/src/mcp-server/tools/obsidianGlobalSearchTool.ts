import { searchNotes as searchObsidianNotes } from '../../services/obsidianRestAPI/methods';
import { wrapTool } from './wrapTool';

/**
 * Search the Obsidian vault for notes that match a text query.
 *
 * @param query - Search query to send to the Obsidian API.
 * @returns Wrapped tool result containing matching note paths and excerpts.
 */
export const searchNotes = wrapTool('searchNotes', async (query: string) => {
  const results = await searchObsidianNotes(query);
  return { data: results };
});
