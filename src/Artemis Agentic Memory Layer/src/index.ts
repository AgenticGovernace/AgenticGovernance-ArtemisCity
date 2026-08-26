import "dotenv/config";
import express from "express";
import cors from "cors";
import { PORT } from "./config";
import { mcpRouter } from "./mcp-server";
import { logger } from "./utils/logger";
import requestLogger from "./utils/requestLogger";

const app = express();

app.use(cors());
app.use(express.json());
app.use(requestLogger);

app.use("/api", mcpRouter);

app.get("/health", (_req, res) => {
  res.status(200).json({ status: "ok" });
});

app.listen(PORT, () => {
  logger.info(`MCP Server running on port ${PORT}`);
  logger.info(`Access at http://localhost:${PORT}`);
});
