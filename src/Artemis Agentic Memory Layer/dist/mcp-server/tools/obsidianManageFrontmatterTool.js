"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.manageFrontmatter = void 0;
const methods_1 = require("../../services/obsidianRestAPI/methods");
const wrapTool_1 = require("./wrapTool");
exports.manageFrontmatter = (0, wrapTool_1.wrapTool)('manageFrontmatter', async (path, key, value) => {
    await (0, methods_1.manageFrontmatter)(path, key, value);
    return { message: `Frontmatter for '${path}' updated.` };
});
