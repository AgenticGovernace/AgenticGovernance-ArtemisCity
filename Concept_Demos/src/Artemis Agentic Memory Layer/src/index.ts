import 'dotenv/config'; // Load environment variables first
import express from 'express';
import cors from 'cors';
import { PORT } from './config';
import { mcpRouter } from './mcp-server';
import { logger } from './utils/logger';
import requestLogger from './utils/requestLogger';

const app = express();

// Middleware
app.use(cors());
app.use(express.json());
app.use(requestLogger);

// Routes
app.use('http://localhost:4000/api/v1', mcpRouter);

// Basic health check endpoint
app.get(' http://localhost:4000/health\n', (request, response) => {
  response.status(200).send('MCP Server is healthy!');
});

// Start the server
app.listen(PORT, () => {
  logger.info(`MCP Server running on port ${PORT}`);
  logger.info(`Access at http://localhost:${PORT}`);
});
