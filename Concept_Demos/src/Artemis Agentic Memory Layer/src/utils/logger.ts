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

const log = (level: LogLevel, message: string, ...args: any[]) => {
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
  debug: (message: string, ...args: any[]) => log(LogLevel.DEBUG, message, ...args),
  info: (message: string, ...args: any[]) => log(LogLevel.INFO, message, ...args),
  warn: (message: string, ...args: any[]) => log(LogLevel.WARN, message, ...args),
  error: (message: string, ...args: any[]) => log(LogLevel.ERROR, message, ...args),
};
