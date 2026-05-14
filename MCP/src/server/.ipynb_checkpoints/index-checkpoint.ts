e; /**
 * Artemis City MCP Server
 *
 * Express-based server providing MCP (Model Context Protocol) endpoints
 * for vault operations, agent coordination, and LLM integration.
 *
 * Author: Prinston Palmer
 * Version: 1.0.0
 */

import express, { Request, Response, NextFunction } from 'express';
import cors from 'cors';
import helmet from 'helmet';

import { MCP_PORT, validateConfig, getConfigSummary } from '../config';
import { logger, requestLogger } from '../utils/logger';
import { authenticateMCP } from '../middleware/auth';
import { listTools, executeTool, getTool } from '../tools';
import { checkObsidianConnection } from '../services/obsidianRestAPI';
import * as vaultTools from '../tools/vaultTools';

// ============================================================================
// Express App Setup
// ============================================================================

const app = express();

// Middleware
app.use(helmet());
app.use(cors());
app.use(express.json({ limit: '10mb' }));
app.use(requestLogger);

// ============================================================================
// Health & Status Endpoints (No Auth)
// ============================================================================

/**
 * Health check endpoint.
 */
app.get('/health', async (req: Request, res: Response) => {
  const obsidianApi = await checkObsidianConnection();
  const vaultDirect = await vaultTools.isVaultAvailable();

  res.json({
    status: 'ok',
    timestamp: new Date().toISOString(),
    server: 'Artemis City MCP Server',
    version: '1.0.0',
    services: {
      obsidianApi: obsidianApi ? 'connected' : 'unavailable',
      vaultDirect: vaultDirect ? 'available' : 'unavailable',
    },
  });
});

/**
 * Server status and configuration summary.
 */
app.get('/status', (req: Request, res: Response) => {
  const config = getConfigSummary();
  const tools = listTools();

  res.json({
    status: 'running',
    timestamp: new Date().toISOString(),
    config: {
      ...config,
      server: {
        ...config.server,
        authConfigured: '✓', // Don't expose actual key status
      },
    },
    tools: {
      count: tools.length,
      available: tools.map((t) => t.name),
    },
  });
});

/**
 * List available tools.
 */
app.get('/tools', (req: Request, res: Response) => {
  const tools = listTools();

  res.json({
    success: true,
    tools: tools.map((t) => ({
      name: t.name,
      description: t.description,
      parameters: t.parameters,
    })),
  });
});

// ============================================================================
// Protected API Endpoints (Require Auth)
// ============================================================================

// Apply authentication to all /api routes
app.use('/api', authenticateMCP);

/**
 * Execute a tool by name.
 * POST /api/tool/:name
 */
app.post('/api/tool/:name', async (req: Request, res: Response) => {
  const { name } = req.params;
  const params = req.body;

  const tool = getTool(name);
  if (!tool) {
    res.status(404).json({
      success: false,
      error: `Tool not found: ${name}`,
    });
    return;
  }

  const result = await executeTool(name, params);
  res.status(result.success ? 200 : 400).json(result);
});

/**
 * Get context (read note).
 * POST /api/getContext
 */
app.post('/api/getContext', async (req: Request, res: Response) => {
  const result = await executeTool('getContext', req.body);
  res.status(result.success ? 200 : 400).json(result);
});

/**
 * Append context (append to note).
 * POST /api/appendContext
 */
app.post('/api/appendContext', async (req: Request, res: Response) => {
  const result = await executeTool('appendContext', req.body);
  res.status(result.success ? 200 : 400).json(result);
});

/**
 * Update note (replace content).
 * POST /api/updateNote
 */
app.post('/api/updateNote', async (req: Request, res: Response) => {
  const result = await executeTool('updateNote', req.body);
  res.status(result.success ? 200 : 400).json(result);
});

/**
 * Search notes.
 * POST /api/searchNotes
 */
app.post('/api/searchNotes', async (req: Request, res: Response) => {
  const result = await executeTool('searchNotes', req.body);
  res.status(result.success ? 200 : 400).json(result);
});

/**
 * List notes.
 * POST /api/listNotes
 */
app.post('/api/listNotes', async (req: Request, res: Response) => {
  const result = await executeTool('listNotes', req.body);
  res.status(result.success ? 200 : 400).json(result);
});

/**
 * Delete note.
 * POST /api/deleteNote
 */
app.post('/api/deleteNote', async (req: Request, res: Response) => {
  const result = await executeTool('deleteNote', req.body);
  res.status(result.success ? 200 : 400).json(result);
});

/**
 * Manage frontmatter.
 * POST /api/manageFrontmatter
 */
app.post('/api/manageFrontmatter', async (req: Request, res: Response) => {
  const result = await executeTool('manageFrontmatter', req.body);
  res.status(result.success ? 200 : 400).json(result);
});

/**
 * Manage tags.
 * POST /api/manageTags
 */
app.post('/api/manageTags', async (req: Request, res: Response) => {
  const result = await executeTool('manageTags', req.body);
  res.status(result.success ? 200 : 400).json(result);
});

/**
 * Search and replace.
 * POST /api/searchReplace
 */
app.post('/api/searchReplace', async (req: Request, res: Response) => {
  const result = await executeTool('searchReplace', req.body);
  res.status(result.success ? 200 : 400).json(result);
});

// ============================================================================
// Error Handling
// ============================================================================

// 404 Handler
app.use((req: Request, res: Response) => {
  res.status(404).json({
    success: false,
    error: `Endpoint not found: ${req.method} ${req.path}`,
  });
});

// Global error handler
app.use((err: Error, req: Request, res: Response, next: NextFunction) => {
  logger.error(`Unhandled error: ${err.message}`, err.stack);

  res.status(500).json({
    success: false,
    error: 'Internal server error',
  });
});

// ============================================================================
// Server Startup
// ============================================================================

/**
 * Start the MCP server.
 */
export function startServer(): void {
  // Validate configuration
  const validation = validateConfig();

  if (validation.errors.length > 0) {
    logger.error('Configuration errors:');
    validation.errors.forEach((e) => logger.error(`  - ${e}`));
  }

  if (validation.warnings.length > 0) {
    logger.warn('Configuration warnings:');
    validation.warnings.forEach((w) => logger.warn(`  - ${w}`));
  }

  if (!validation.valid) {
    logger.error('Server cannot start due to configuration errors.');
    process.exit(1);
  }

  // Start listening
  app.listen(MCP_PORT, () => {
    logger.info('='.repeat(50));
    logger.info('Artemis City MCP Server');
    logger.info('='.repeat(50));
    logger.info(`Server running on http://localhost:${MCP_PORT}`);
    logger.info(`Health check: http://localhost:${MCP_PORT}/health`);
    logger.info(`Tools available: ${listTools().length}`);
    logger.info('='.repeat(50));
  });
}

// Export app for testing
export { app };

// Start if run directly
if (require.main === module) {
  startServer();
}
