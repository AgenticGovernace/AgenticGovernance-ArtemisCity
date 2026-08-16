# Build only the mounted Express workspace from the checked-in Yarn lock.
FROM node:24-bookworm-slim AS builder

WORKDIR /workspace
COPY package.json yarn.lock ./
COPY app/api/package.json ./app/api/package.json
COPY app/web/frontend/package.json ./app/web/frontend/package.json
RUN corepack enable \
    && corepack prepare yarn@1.22.22 --activate \
    && yarn install --frozen-lockfile
COPY app/api/ ./app/api/
RUN yarn workspace artemis-city-express-api build

# Install production-only Node dependencies without carrying TypeScript/Jest.
FROM node:24-bookworm-slim AS production-dependencies

WORKDIR /workspace
COPY package.json yarn.lock ./
COPY app/api/package.json ./app/api/package.json
COPY app/web/frontend/package.json ./app/web/frontend/package.json
RUN corepack enable \
    && corepack prepare yarn@1.22.22 --activate \
    && yarn install --frozen-lockfile --production --ignore-scripts

# Express invokes the Python bridge as a child process. Package the bridge's
# actual Python dependencies, including the PostgreSQL driver used by Neon.
FROM node:24-bookworm-slim

ENV NODE_ENV=production \
    ARTEMIS_REPO_ROOT=/srv/artemis \
    ARTEMIS_PYTHON=/opt/artemis-venv/bin/python \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        python3 \
        python3-venv \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/artemis
COPY requirements-bridge.txt ./
RUN python3 -m venv /opt/artemis-venv \
    && /opt/artemis-venv/bin/pip install --no-cache-dir \
        -r requirements-bridge.txt

COPY --from=production-dependencies /workspace/node_modules/ ./node_modules/
COPY --from=builder /workspace/app/api/dist/ ./app/api/dist/
COPY app/api/package.json ./app/api/package.json
COPY src/ ./src/

RUN mkdir -p /srv/artemis/data \
    && chown -R node:node /srv/artemis
USER node

EXPOSE 4000

CMD ["node", "app/api/dist/index.js"]

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD node -e "const p=process.env.API_PORT||4000; require('http').get('http://localhost:'+p+'/health', (res) => res.statusCode === 200 ? process.exit(0) : process.exit(1))"
