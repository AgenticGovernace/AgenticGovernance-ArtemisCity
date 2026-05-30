FROM node:20-alpine AS builder

WORKDIR /src

COPY package*.json tsconfig.json ./
RUN npm ci

COPY src ./src
RUN npm run build

FROM node:20-alpine

WORKDIR /src
ENV NODE_ENV=production

COPY package*.json ./
RUN npm ci --omit=dev && npm cache clean --force

COPY --from=builder /src/dist ./dist

EXPOSE 3000
USER node

CMD ["node", "dist/index.js"]
