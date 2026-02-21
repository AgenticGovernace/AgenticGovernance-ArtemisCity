import 'dotenv/config'; // Load environment variables first
import express from 'express';
import cors, { CorsOptions } from 'cors';
import { CORS_ORIGINS, PORT } from './config';
import { mcpRouter } from './mcp-server';
import { requestLogger, logger } from './utils/logger';

const app = express();

// Middleware
const corsOptions: CorsOptions = {
  origin: (origin, callback) => {
    // Non-browser clients (curl/server-to-server) generally have no origin.
    if (!origin) {
      callback(null, true);
      return;
    }

    if (CORS_ORIGINS.includes(origin)) {
      callback(null, true);
      return;
    }

    callback(new Error('CORS origin denied'));
  },
};

app.use(cors(corsOptions));
app.use(express.json());
app.use(requestLogger);

// Routes
app.use('/api', mcpRouter);

// Basic health check endpoint
app.get('/health', (req, res) => {
  res.status(200).send('MCP Server is healthy!');
});

// Start the server
app.listen(PORT, () => {
  logger.info(`MCP Server running on port ${PORT}`);
  logger.info(`Access at http://localhost:${PORT}`);
});
