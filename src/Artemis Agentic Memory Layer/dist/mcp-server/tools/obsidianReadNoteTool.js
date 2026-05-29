"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.getContext = void 0;
const methods_1 = require("../../services/obsidianRestAPI/methods");
const wrapTool_1 = require("./wrapTool");
exports.getContext = (0, wrapTool_1.wrapTool)('getContext', async (path) => {
    const content = await (0, methods_1.readNote)(path);
    return { data: { path, content } };
});
