"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.mcpRouter = void 0;
const express_1 = require("express");
const auth_1 = __importDefault(require("./middleware/auth"));
const obsidianReadNoteTool_1 = require("./tools/obsidianReadNoteTool");
const obsidianUpdateNoteTool_1 = require("./tools/obsidianUpdateNoteTool");
const obsidianGlobalSearchTool_1 = require("./tools/obsidianGlobalSearchTool");
const obsidianListNotesTool_1 = require("./tools/obsidianListNotesTool");
const obsidianDeleteNoteTool_1 = require("./tools/obsidianDeleteNoteTool");
const obsidianManageFrontmatterTool_1 = require("./tools/obsidianManageFrontmatterTool");
const obsidianManageTagsTool_1 = require("./tools/obsidianManageTagsTool");
const obsidianSearchReplaceTool_1 = require("./tools/obsidianSearchReplaceTool");
const logger_1 = require("../utils/logger");
const mcpRouter = (0, express_1.Router)();
exports.mcpRouter = mcpRouter;
mcpRouter.use(auth_1.default);
const handle = (name, required, fn) => async (req, res) => {
    const missing = required.find((k) => req.body?.[k] === undefined);
    if (missing) {
        res.status(400).json({ success: false, error: `Missing field: ${missing}` });
        return;
    }
    logger_1.logger.debug(`Received ${name} request`, req.body);
    const result = await fn(req.body);
    res.status(result.success ? 200 : 500).json(result);
};
mcpRouter.post('/getContext', handle('getContext', ['path'], (b) => (0, obsidianReadNoteTool_1.getContext)(b.path)));
mcpRouter.post('/appendContext', handle('appendContext', ['path', 'content'], (b) => (0, obsidianUpdateNoteTool_1.appendContext)(b.path, b.content)));
mcpRouter.post('/updateNote', handle('updateNote', ['path', 'content'], (b) => (0, obsidianUpdateNoteTool_1.updateNote)(b.path, b.content)));
mcpRouter.post('/searchNotes', handle('searchNotes', ['query'], (b) => (0, obsidianGlobalSearchTool_1.searchNotes)(b.query)));
mcpRouter.post('/listNotes', handle('listNotes', [], () => (0, obsidianListNotesTool_1.listNotes)()));
mcpRouter.post('/deleteNote', handle('deleteNote', ['path'], (b) => (0, obsidianDeleteNoteTool_1.deleteNote)(b.path)));
mcpRouter.post('/manageFrontmatter', handle('manageFrontmatter', ['path', 'key', 'value'], (b) => (0, obsidianManageFrontmatterTool_1.manageFrontmatter)(b.path, b.key, b.value)));
mcpRouter.post('/manageTags', async (req, res) => {
    const { path, tags, action } = req.body ?? {};
    if (!path || !Array.isArray(tags) || !obsidianManageTagsTool_1.MANAGE_TAGS_ACTIONS.includes(action)) {
        res.status(400).json({
            success: false,
            error: `Missing note path, tags (array), or invalid action (${obsidianManageTagsTool_1.MANAGE_TAGS_ACTIONS.join('/')}).`,
        });
        return;
    }
    logger_1.logger.debug(`Received manageTags request for ${path}`);
    const result = await (0, obsidianManageTagsTool_1.manageTags)(path, tags, action);
    res.status(result.success ? 200 : 500).json(result);
});
mcpRouter.post('/searchReplace', handle('searchReplace', ['path', 'search', 'replace'], (b) => (0, obsidianSearchReplaceTool_1.searchReplace)(b.path, b.search, b.replace)));
