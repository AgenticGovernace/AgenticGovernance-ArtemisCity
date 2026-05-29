"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.deleteNote = void 0;
const methods_1 = require("../../services/obsidianRestAPI/methods");
const wrapTool_1 = require("./wrapTool");
exports.deleteNote = (0, wrapTool_1.wrapTool)('deleteNote', async (path) => {
    await (0, methods_1.deleteNote)(path);
    return { message: `Note '${path}' deleted successfully.` };
});
