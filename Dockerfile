# Stage 1: Builder - Install dependencies and build the application
FROM node:24-alpine AS builder

# Set the working directory in the container
WORKDIR /src

# Copy package.json and package-lock.json first to leverage Docker cache
# This ensures that npm install is only re-run if dependencies change.
# Use `npm ci` (not `npm install`) so the build honors the lockfile
# exactly -- required for reproducible CI/production builds.
COPY package*.json ./
RUN npm ci
# Install application dependencies (including devDependencies — TypeScript
# and @types/* live there and the next ``npm run build`` step requires
# them). The production stage below installs a separate prod-only copy.
# Copy the rest of the application code
COPY . .

# Build the TypeScript project
RUN npm run build

# Stage 2: Production - Create a lean image with only the necessary files
FROM node:24-alpine

# Set the working directory in the container
WORKDIR /src

# Set environment variables for production
ENV NODE_ENV=production \
    ARTEMIS_REPO_ROOT=/src \
    ARTEMIS_PYTHON=python3

# Express spawns ``python3 -m src.api_bridge`` for every registry /
# governance call (see app/api/lib/pythonBridge.ts). The bridge itself is
# stdlib-only by design, so we install just the interpreter -- no pip
# packages -- and copy the ``src`` tree so the import resolves at cwd.
RUN apk add --no-cache python3

# Copy only the compiled application from the builder stage and install a
# fresh production-only node_modules. Doing the install here (instead of
# COPYing the builder's node_modules) keeps the final image free of dev
# tooling like TypeScript and @types/*.
COPY --from=builder /src/dist/ ./dist
COPY --from=builder /src/package.json /src/package-lock.json ./
RUN npm ci --omit=dev

# Copy the Python bridge tree last so changes to it don't invalidate the
# npm-install cache layer.
COPY --from=builder /src/src/ ./src

# Expose the port the Express API listens on. Matches the API_PORT default
# in app/api/index.ts (4000) and avoids the 3000 collision with Grafana
# in docker-compose.yml. Override at runtime with `-e API_PORT=...`.
EXPOSE 4000

# Create app directory with proper permissions for node user
RUN chown -R node:node /src

# Run as a non-root user for security best practices
# The node:alpine image typically creates a 'node' user with appropriate permissions
USER node

# Run the compiled application
CMD ["npm", "start"]

# Healthcheck honors `API_PORT` overrides so the probe matches whatever
# port app/api/index.ts is actually listening on (default 4000).
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 CMD node -e "const p=process.env.API_PORT||4000; require('http').get('http://localhost:'+p+'/health', (res) => res.statusCode === 200 ? process.exit(0) : process.exit(1))"

