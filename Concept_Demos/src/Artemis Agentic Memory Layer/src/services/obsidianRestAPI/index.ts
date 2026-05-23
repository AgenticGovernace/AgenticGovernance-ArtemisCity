import axios, { AxiosInstance, AxiosResponse, AxiosError } from 'axios';
import https from 'https';
import { OBSIDIAN_BASE_URL, OBSIDIAN_API_KEY } from '../../config';
import { logger } from '../../utils/logger';

// Obsidian Local REST API ships with a self-signed cert on https://127.0.0.1:27124,
// so TLS verification is disabled. Only safe because the target is a localhost dev plugin.
const obsidianAPI: AxiosInstance = axios.create({
  baseURL: OBSIDIAN_BASE_URL,
  headers: {
    'Authorization': `Bearer ${OBSIDIAN_API_KEY}`,
    'Content-Type': 'application/json',
  },
  httpsAgent: new https.Agent({ rejectUnauthorized: false, keepAlive: true }),
});

// Add a request interceptor
obsidianAPI.interceptors.request.use(
  (config) => {
    logger.debug(`Obsidian API Request: ${config.method?.toUpperCase()} ${config.url}`);
    return config;
  },
  (error) => {
    logger.error(`Obsidian API Request Error: ${error.message}`);
    return Promise.reject(error);
  }
);

// Add a response interceptor
obsidianAPI.interceptors.response.use(
  (response: AxiosResponse) => {
    logger.debug(`Obsidian API Response: ${response.status} ${response.config.url}`);
    return response;
  },
  (error: AxiosError) => {
    if (error.response) {
      logger.error(`Obsidian API Response Error - Status: ${error.response.status}, Data: ${JSON.stringify(error.response.data)}`);
    } else if (error.request) {
      logger.error(`Obsidian API Response Error - No response received: ${error.message}`);
    } else {
      logger.error(`Obsidian API Request Setup Error: ${error.message}`);
    }
    return Promise.reject(error);
  }
);

export { obsidianAPI };
