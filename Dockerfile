# Stage 1: Builder - Install dependencies and build the application
FROM node:24-alpine AS builder

# Set the working directory in the container
WORKDIR /src

# Copy package.json and package-lock.json first to leverage Docker cache
# This ensures that npm install is only re-run if dependencies change
COPY package*.json ./

# Install application dependencies (including devDependencies — TypeScript
# and @types/* live there and the next ``npm run build`` step requires
# them). The production stage below installs a separate prod-only copy.
RUN npm ci

# Copy the rest of the application code
COPY . .

# Build the TypeScript project
RUN npm run build

# Stage 2: Production - Create a lean image with only the necessary files
FROM node:24-alpine

# Set the working directory in the container
WORKDIR /app

# Set environment variables for production
ENV NODE_ENV=production


# Copy only the compiled application from the builder stage and install a
# fresh production-only node_modules. Doing the install here (instead of
# COPYing the builder's node_modules) keeps the final image free of dev
# tooling like TypeScript and @types/*.
COPY --from=builder /src/dist/ ./dist
COPY --from=builder /src/package.json /src/package-lock.json ./
RUN npm ci --omit=dev

# Expose the port the app runs on
EXPOSE 3000

# Run as a non-root user for security best practices
# The node:alpine image typically creates a 'node' user with appropriate permissions
USER node

# Run the compiled application
CMD ["npm", "start"]
# Healthcheck to ensure the container is running correctly
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD node -e "require('http').get('http://localhost:3000/health', (res) => res.statusCode === 200 ? process.exit(0) : process.exit(1))";

