import { manageTags as manageObsidianTags } from '../../services/obsidianRestAPI/methods';
import { wrapTool } from './wrapTool';

export const MANAGE_TAGS_ACTIONS = ['add', 'remove'] as const;
export type ManageTagsAction = (typeof MANAGE_TAGS_ACTIONS)[number];

const MANAGE_TAGS_ACTION_PAST_TENSE: Record<ManageTagsAction, string> = {
  add: 'added',
  remove: 'removed',
};

/**
 * Add or remove tags on a note in the Obsidian vault.
 *
 * @param path - Vault-relative note path to update.
 * @param tags - Tags to add to or remove from the note.
 * @param action - Whether the tags should be added or removed.
 * @returns Wrapped tool result containing the tag update status message.
 */
export const manageTags = wrapTool(
  'manageTags',
  async (path: string, tags: string[], action: ManageTagsAction) => {
    await manageObsidianTags(path, tags, action);
    return {
      message: `Tags for '${path}' ${MANAGE_TAGS_ACTION_PAST_TENSE[action]} successfully.`,
    };
  },
);
