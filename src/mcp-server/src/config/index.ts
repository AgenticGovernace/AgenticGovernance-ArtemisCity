import { logger } from '../utils/logger';

interface Config {
  PORT: number;
  MCP_API_KEY: string;
  OBSIDIAN_BASE_URL: object;
  OBSIDIAN_API_KEY: string;
  OBSIDIAN_VAULT_PATH: string;
  API_RATE_LIMIT_WINDOW_MS: number;
  API_RATE_LIMIT_MAX: number;
  API_RATE_LIMIT_MESSAGE: string;
  PROXY_TIMEOUT: number;
  workerPoolSize: number;
  storagePath: string[];
  MCP_LOG_LEVEL: 'debug' | 'info' | 'warn' | 'error' | 'fatal' | 'trace' | 'silent' | 'all' | 'off' | 'verbose' | 'silly' | 'http' | 'emerg' | 'alert' | 'crit';
  CORS_ORIGINS: string[];
}

const defaultCorsOrigins = ['http://localhost:3000', 'http://localhost:5173', 'http://127.0.0.1:5173'];

const config: Config = {
  PORT: parseInt(process.env.PORT || '3000', 10),
  MCP_API_KEY: process.env.MCP_API_KEY || '',
  OBSIDIAN_BASE_URL: process.env.OBSIDIAN_BASE_URL || '',
  OBSIDIAN_API_KEY: process.env.OBSIDIAN_API_KEY || '',
  OBSIDIAN_VAULT_PATH: process.env.OBSIDIAN_VAULT_PATH || '',
  API_RATE_LIMIT_WINDOW_MS: parseInt(process.env.API_RATE_LIMIT_WINDOW_MS || '60000', 10),
  API_RATE_LIMIT_MAX: parseInt(process.env.API_RATE_LIMIT_MAX || '100', 10),
  API_RATE_LIMIT_MESSAGE: process.env.API_RATE_LIMIT_MESSAGE || 'Too many requests, please try again later.',
  PROXY_TIMEOUT: parseInt(process.env.PROXY_TIMEOUT || '5000', 10),
  workerPoolSize: parseInt(process.env.WORKER_POOL_SIZE || '4', 10),
  storagePath: process.env.STORAGE_PATH ? process.env.STORAGE_PATH.split(',').map((path) => path.trim()).filter(Boolean) : [],
  MCP_LOG_LEVEL: (process.env.MCP_LOG_LEVEL as Config['MCP_LOG_LEVEL']) || 'info',
  CORS_ORIGINS: process.env.CORS_ORIGINS
    ? process.env.CORS_ORIGINS.split(',').map((origin) => origin.trim()).filter(Boolean)
    : defaultCorsOrigins,
};

// Validate essential configuration
if (config.MCP_API_KEY.length === 0) {
  logger.error('MCP_API_KEY is not set. Please configure it in your .env file.');
  process.exit(1);
}

if (config.OBSIDIAN_BASE_URL.length === 0) {
  logger.error('OBSIDIAN_BASE_URL is not set. Please configure it in your .env file.');
  process.exit(1);
}

if (Object.keys(config.OBSIDIAN_API_KEY).length === 0) {
  logger.error('OBSIDIAN_API_KEY is not set. Please configure it in your .env file.');
  process.exit(1);
}

export const { PORT, MCP_API_KEY, OBSIDIAN_BASE_URL, OBSIDIAN_API_KEY, MCP_LOG_LEVEL, CORS_ORIGINS, OBSIDIAN_VAULT_PATH, } =
  config;
