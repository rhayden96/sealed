FROM node:22-alpine@sha256:b6f26b36c8ff49624cfdac716b8ea1138d606df02586a77d364bb5536a634f85 AS build

WORKDIR /app/apps/target-web
COPY apps/target-web/package.json apps/target-web/package-lock.json ./
RUN npm ci
COPY apps/target-web/ ./
COPY packages/web/ /app/packages/web/
RUN npm run build

FROM node:22-alpine@sha256:b6f26b36c8ff49624cfdac716b8ea1138d606df02586a77d364bb5536a634f85
WORKDIR /app
COPY --from=build /app/apps/target-web/dist ./dist
COPY packages/web/server.mjs ./server.mjs
ENV WEB_MODE=target PORT=5174
USER node
EXPOSE 5174
CMD ["node", "server.mjs"]
