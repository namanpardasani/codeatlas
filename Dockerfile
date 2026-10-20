# API + built web app in one image (single origin: the API lives under /api, the SPA is served by the same process).
# Build from the repository root:  docker build -t codeatlas-app .
FROM node:22-slim AS web
WORKDIR /w
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web/ ./
RUN npm run build

FROM node:22-slim AS api
WORKDIR /a
COPY apps/api/package.json apps/api/package-lock.json ./
RUN npm ci
COPY apps/api/tsconfig.json ./
COPY apps/api/src ./src
RUN npx tsc -p tsconfig.json && npm prune --omit=dev

FROM node:22-slim
ENV NODE_ENV=production WEB_DIST=/app/web
WORKDIR /app
COPY --from=api /a/node_modules ./node_modules
COPY --from=api /a/dist ./dist
COPY apps/api/package.json ./
COPY --from=web /w/dist ./web
USER node
EXPOSE 4000
HEALTHCHECK --interval=30s --timeout=3s CMD node -e "fetch('http://127.0.0.1:'+(process.env.API_PORT||4000)+'/api/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
CMD ["node", "dist/server.js"]
