import { Request, Response, Router } from "express";
import authenticateMCP from "./middleware/auth";
import { getContext } from "./tools/obsidianReadNoteTool";
import { appendContext, updateNote } from "./tools/obsidianUpdateNoteTool";
import { searchNotes } from "./tools/obsidianGlobalSearchTool";
import { listNotes } from "./tools/obsidianListNotesTool";
import { deleteNote } from "./tools/obsidianDeleteNoteTool";
import { manageFrontmatter } from "./tools/obsidianManageFrontmatterTool";
import {
  manageTags,
  MANAGE_TAGS_ACTIONS,
  ManageTagsAction,
} from "./tools/obsidianManageTagsTool";
import { searchReplace } from "./tools/obsidianSearchReplaceTool";
import { logger } from "../utils/logger";

type ToolResult = { success: boolean; [k: string]: unknown };

const mcpRouter = Router();
mcpRouter.use(authenticateMCP);

const handle =
  (
    name: string,
    required: string[],
    fn: (body: Record<string, any>) => Promise<ToolResult>,
  ) =>
  async (req: Request, res: Response): Promise<void> => {
    const missing = required.find((k) => req.body?.[k] === undefined);
    if (missing) {
      res
        .status(400)
        .json({ success: false, error: `Missing field: ${missing}` });
      return;
    }
    logger.debug(`Received ${name} request`, req.body);
    const result = await fn(req.body);
    res.status(result.success ? 200 : 500).json(result);
  };

mcpRouter.post(
  "/getContext",
  handle("getContext", ["path"], (b) => getContext(b.path)),
);
mcpRouter.post(
  "/appendContext",
  handle("appendContext", ["path", "content"], (b) =>
    appendContext(b.path, b.content),
  ),
);
mcpRouter.post(
  "/updateNote",
  handle("updateNote", ["path", "content"], (b) =>
    updateNote(b.path, b.content),
  ),
);
mcpRouter.post(
  "/searchNotes",
  handle("searchNotes", ["query"], (b) => searchNotes(b.query)),
);
mcpRouter.post(
  "/listNotes",
  handle("listNotes", [], () => listNotes()),
);
mcpRouter.post(
  "/deleteNote",
  handle("deleteNote", ["path"], (b) => deleteNote(b.path)),
);
mcpRouter.post(
  "/manageFrontmatter",
  handle("manageFrontmatter", ["path", "key", "value"], (b) =>
    manageFrontmatter(b.path, b.key, b.value),
  ),
);
mcpRouter.post("/manageTags", async (req, res) => {
  const { path, tags, action } = req.body ?? {};
  if (!path || !Array.isArray(tags) || !MANAGE_TAGS_ACTIONS.includes(action)) {
    res.status(400).json({
      success: false,
      error: `Missing note path, tags (array), or invalid action (${MANAGE_TAGS_ACTIONS.join("/")}).`,
    });
    return;
  }
  logger.debug(`Received manageTags request for ${path}`);
  const result = await manageTags(path, tags, action as ManageTagsAction);
  res.status(result.success ? 200 : 500).json(result);
});
mcpRouter.post(
  "/searchReplace",
  handle("searchReplace", ["path", "search", "replace"], (b) =>
    searchReplace(b.path, b.search, b.replace),
  ),
);

export { mcpRouter };
