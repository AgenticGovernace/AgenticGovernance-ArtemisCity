process.env.NODE_ENV = 'development';
process.env.SKIP_AUTH = 'true';
process.env.MCP_API_KEY = process.env.MCP_API_KEY || 'test-api-key';
process.env.ARTEMIS_REPO_ROOT = process.env.ARTEMIS_REPO_ROOT || process.cwd();
process.env.ARTEMIS_PYTHON = process.env.ARTEMIS_PYTHON || '.venv/bin/python';
