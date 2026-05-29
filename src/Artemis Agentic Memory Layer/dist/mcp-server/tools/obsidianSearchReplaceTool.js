"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.searchReplace = void 0;
const methods_1 = require("../../services/obsidianRestAPI/methods");
const wrapTool_1 = require("./wrapTool");
exports.searchReplace = (0, wrapTool_1.wrapTool)('searchReplace', async (path, search, replace) => {
    const content = await (0, methods_1.searchReplace)(path, search, replace);
    return {
        data: { path, content },
        message: `Search and replace in '${path}' successful.`,
    };
});
