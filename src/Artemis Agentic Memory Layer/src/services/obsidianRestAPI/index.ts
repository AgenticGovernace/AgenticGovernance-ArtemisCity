import axios, { AxiosInstance, AxiosResponse, AxiosError } from 'axios';
import https from 'https';
import fs from 'fs';
import { OBSIDIAN_BASE_URL, OBSIDIAN_API_KEY } from '../../config';
import { logger } from '../../utils/logger';

// Keep TLS certificate validation enabled. For local self-signed certs,
// trust a specific CA/cert via OBSIDIAN_CA_CERT instead of disabling validation.
const obsidianCACert = process.env.OBSIDIAN_CA_CERT
  ? fs.readFileSync(process.env.OBSIDIAN_CA_CERT)
  : undefined;

const obsidianAPI: AxiosInstance = axios.create({
  baseURL: OBSIDIAN_BASE_URL,
  headers: {
    'Authorization': `Bearer ${OBSIDIAN_API_KEY}`,
    'Content-Type': 'application/json',
  },
  httpsAgent: new https.Agent({ keepAlive: true, ca: obsidianCACert }),
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
