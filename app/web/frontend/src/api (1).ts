/**
 * API Client for MCP Dashboard
 *
 * Provides functions to interact with the MCP backend API.
 * All endpoints are proxied through Vite dev server during development.
 *
 * @module api
 */

/** Base URL for API endpoints (proxied by Vite in development) */
const API_BASE_URL = '/api';

/**
 * Fetch all registered agents from the MCP server.
 *
 * @returns Promise resolving to an array of agent objects
 * @throws Error if the request fails
 */
export const fetchAgents = async () => {
  const response = await fetch(`${API_BASE_URL}/agents`);
  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`);
  }
  return response.json();
};

/**
 * Fetch all tasks from the Obsidian vault.
 *
 * @returns Promise resolving to an array of task objects
 * @throws Error if the request fails
 */
export const fetchTasks = async () => {
  const response = await fetch(`${API_BASE_URL}/tasks`);
  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`);
  }
  return response.json();
};

/**
 * Create a new task in the Obsidian vault.
 *
 * @param taskData - Task data including agent, title, context, and keywords
 * @returns Promise resolving to the created task object
 * @throws Error if the request fails
 */
export const createNewTask = async (taskData: any) => {
  const response = await fetch(`${API_BASE_URL}/tasks`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(taskData),
  });
  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`);
  }
  return response.json();
};

/**
 * Fetch all available reports from the MCP server.
 *
 * @returns Promise resolving to an array of report summary objects
 * @throws Error if the request fails
 */
export const fetchReports = async () => {
  const response = await fetch(`${API_BASE_URL}/reports`);
  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`);
  }
  return response.json();
};

/**
 * Fetch the content of a specific report.
 *
 * @param filename - Name of the report file to fetch
 * @returns Promise resolving to the report content object
 * @throws Error if the request fails
 */
export const fetchReportContent = async (filename: string) => {
  const response = await fetch(`${API_BASE_URL}/reports/${filename}`);
  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`);
  }
  return response.json();
};

/**
 * Execute a single pending task by its relative path.
 *
 * @param relativePath - Path to the task file in the Obsidian vault
 * @returns Promise resolving to the execution result
 * @throws Error if the request fails
 */
export const executePendingTask = async (relativePath: string) => {
  const response = await fetch(`${API_BASE_URL}/execute-task`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ relative_path: relativePath }),
  });
  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`);
  }
  return response.json();
};

/**
 * Execute all pending tasks in batch.
 *
 * @returns Promise resolving to a summary with completed, failed, and skipped counts
 * @throws Error if the request fails
 */
export const executeAllPendingTasks = async () => {
  const response = await fetch(`${API_BASE_URL}/execute-all-pending`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
  });
  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`);
  }
  return response.json();
};
