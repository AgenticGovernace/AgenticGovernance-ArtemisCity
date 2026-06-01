import { manageFrontmatter as manageObsidianFrontmatter } from '../../services/obsidianRestAPI/methods';
import { wrapTool } from './wrapTool';

/**
 * Replace a frontmatter key on a note in the Obsidian vault.
 *
 * @param path - Vault-relative note path to update.
 * @param key - Frontmatter key to replace.
 * @param value - JSON-serializable value to store under the key.
 * @returns Wrapped tool result containing the frontmatter update status message.
 */
export const manageFrontmatter = wrapTool(
  'manageFrontmatter',
  async (path: string, key: string, value: unknown) => {
    await manageObsidianFrontmatter(path, key, value);
    return { message: `Frontmatter for '${path}' updated.` };
  },
);
