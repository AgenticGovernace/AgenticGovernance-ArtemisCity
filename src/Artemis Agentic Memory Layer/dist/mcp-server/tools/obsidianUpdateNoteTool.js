"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.updateNote = exports.appendContext = void 0;
const methods_1 = require("../../services/obsidianRestAPI/methods");
const wrapTool_1 = require("./wrapTool");
exports.appendContext = (0, wrapTool_1.wrapTool)('appendContext', async (path, content) => {
    await (0, methods_1.updateNote)(path, content, { append: true });
    return { message: `Content appended to note '${path}'.` };
});
exports.updateNote = (0, wrapTool_1.wrapTool)('updateNote', async (path, content) => {
    await (0, methods_1.updateNote)(path, content, { append: false });
    return { message: `Note '${path}' updated.` };
});
