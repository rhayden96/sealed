FROM node:22-alpine@sha256:b6f26b36c8ff49624cfdac716b8ea1138d606df02586a77d364bb5536a634f85 AS build

WORKDIR /app/apps/web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web/ ./
COPY packages/web/ /app/packages/web/
COPY fixtures/ /app/fixtures/
RUN npm run build

FROM node:22-alpine@sha256:b6f26b36c8ff49624cfdac716b8ea1138d606df02586a77d364bb5536a634f85
WORKDIR /app
COPY --from=build /app/apps/web/dist ./dist
COPY packages/web/server.mjs ./server.mjs
ENV WEB_MODE=console PORT=5173
USER node
EXPOSE 5173
CMD ["node", "server.mjs"]
