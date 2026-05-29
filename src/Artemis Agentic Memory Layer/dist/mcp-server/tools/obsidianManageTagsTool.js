"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.manageTags = exports.MANAGE_TAGS_ACTIONS = void 0;
const methods_1 = require("../../services/obsidianRestAPI/methods");
const wrapTool_1 = require("./wrapTool");
exports.MANAGE_TAGS_ACTIONS = ['add', 'remove'];
exports.manageTags = (0, wrapTool_1.wrapTool)('manageTags', async (path, tags, action) => {
    await (0, methods_1.manageTags)(path, tags, action);
    return { message: `Tags for '${path}' ${action}ed successfully.` };
});
