# syntax=docker/dockerfile:1.7

# ---- Build stage ----
FROM node:20-slim AS builder

WORKDIR /src

COPY package*.json tsconfig.json ./
RUN npm ci

COPY src ./src
RUN npm run build

# ---- Runtime stage ----
FROM node:20-alpine

WORKDIR /src
ENV NODE_ENV=production

COPY package*.json ./
RUN npm ci --omit=dev && npm cache clean --force

COPY --from=builder /src/dist ./dist

EXPOSE 3000
USER node

# BusyBox wget is bundled with node:20-alpine and is used by the
# compose healthcheck against the /health endpoint exposed by index.ts.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -qO- http://localhost:3000/health || exit 1

CMD ["node", "dist/index.js"]
