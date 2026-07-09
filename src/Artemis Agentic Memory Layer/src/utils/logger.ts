enum LogLevel {
  DEBUG = 0,
  INFO = 1,
  WARN = 2,
  ERROR = 3,
}

const LEVEL_FROM_ENV: Record<string, LogLevel> = {
  debug: LogLevel.DEBUG,
  info: LogLevel.INFO,
  warn: LogLevel.WARN,
  error: LogLevel.ERROR,
};

const currentLogLevel: LogLevel =
  LEVEL_FROM_ENV[(process.env.MCP_LOG_LEVEL ?? 'info').toLowerCase()] ?? LogLevel.INFO;

const log = (level: LogLevel, message: string, ...args: unknown[]) => {
  if (level < currentLogLevel) return;

  const formatted = `[${new Date().toISOString()}] [${LogLevel[level]}] ${message}`;

  switch (level) {
    case LogLevel.DEBUG:
      console.debug(formatted, ...args);
      break;
    case LogLevel.INFO:
      console.info(formatted, ...args);
      break;
    case LogLevel.WARN:
      console.warn(formatted, ...args);
      break;
    case LogLevel.ERROR:
      console.error(formatted, ...args);
      break;
  }
};

export const logger = {
  debug: (message: string, ...args: unknown[]) => log(LogLevel.DEBUG, message, ...args),
  info: (message: string, ...args: unknown[]) => log(LogLevel.INFO, message, ...args),
  warn: (message: string, ...args: unknown[]) => log(LogLevel.WARN, message, ...args),
  error: (message: string, ...args: unknown[]) => log(LogLevel.ERROR, message, ...args),
};

/**
 * Sanitize values before logging to prevent log injection/forgery.
 * Strips CR/LF and other control characters and truncates long values.
 */
export const sanitizeForLog = (value: unknown): string => {
  if (value === null || value === undefined) {
    return '';
  }
  const text = typeof value === 'string' ? value : safeStringify(value);
  const cleaned = text.replace(/[\r\n]+/g, ' ').replace(/[\x00-\x1f\x7f]/g, '');
  return cleaned.length > 500 ? `${cleaned.slice(0, 500)}…` : cleaned;
};

const safeStringify = (value: unknown): string => {
  try {
    return JSON.stringify(value) ?? String(value);
  } catch {
    return String(value);
  }
};
