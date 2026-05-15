import { manageFrontmatter as manageObsidianFrontmatter } from '../../services/obsidianRestAPI/methods';
import { wrapTool } from './wrapTool';

export const manageFrontmatter = wrapTool(
  'manageFrontmatter',
  async (path: string, key: string, value: unknown) => {
    await manageObsidianFrontmatter(path, key, value);
    return { message: `Frontmatter for '${path}' updated.` };
  },
);
