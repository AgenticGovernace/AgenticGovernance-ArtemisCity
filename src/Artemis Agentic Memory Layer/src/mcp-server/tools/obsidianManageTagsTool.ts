import { manageTags as manageObsidianTags } from '../../services/obsidianRestAPI/methods';
import { wrapTool } from './wrapTool';

export const MANAGE_TAGS_ACTIONS = ['add', 'remove'] as const;
export type ManageTagsAction = (typeof MANAGE_TAGS_ACTIONS)[number];

const MANAGE_TAGS_ACTION_PAST_TENSE: Record<ManageTagsAction, string> = {
  add: 'added',
  remove: 'removed',
};

export const manageTags = wrapTool(
  'manageTags',
  async (path: string, tags: string[], action: ManageTagsAction) => {
    await manageObsidianTags(path, tags, action);
    return {
      message: `Tags for '${path}' ${MANAGE_TAGS_ACTION_PAST_TENSE[action]} successfully.`,
    };
  },
);
