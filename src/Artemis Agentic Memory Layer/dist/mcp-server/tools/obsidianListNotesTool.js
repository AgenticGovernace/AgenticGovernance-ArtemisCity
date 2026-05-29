"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.listNotes = void 0;
const methods_1 = require("../../services/obsidianRestAPI/methods");
const wrapTool_1 = require("./wrapTool");
exports.listNotes = (0, wrapTool_1.wrapTool)('listNotes', async () => {
    const notes = await (0, methods_1.listNotes)();
    return { data: notes };
});
