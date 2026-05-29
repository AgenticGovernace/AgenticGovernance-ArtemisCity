"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.searchNotes = void 0;
const methods_1 = require("../../services/obsidianRestAPI/methods");
const wrapTool_1 = require("./wrapTool");
exports.searchNotes = (0, wrapTool_1.wrapTool)('searchNotes', async (query) => {
    const results = await (0, methods_1.searchNotes)(query);
    return { data: results };
});
