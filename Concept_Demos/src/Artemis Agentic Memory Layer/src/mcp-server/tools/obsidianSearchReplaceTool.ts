import { searchReplace as obsidianSearchReplace } from '../../services/obsidianRestAPI/methods';
import { wrapTool } from './wrapTool';

export const searchReplace = wrapTool(
  'searchReplace',
  async (path: string, search: string, replace: string) => {
    const content = await obsidianSearchReplace(path, search, replace);
    return {
      data: { path, content },
      message: `Search and replace in '${path}' successful.`,
    };
  },
);
