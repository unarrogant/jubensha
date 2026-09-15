FROM node:20-bookworm-slim AS build
WORKDIR /app
ENV NODE_ENV=development NPM_CONFIG_PRODUCTION=false
COPY frontend/package*.json ./
RUN npm ci \
    --include=dev \
    --no-audit \
    --no-fund \
    --registry=https://registry.npmmirror.com \
    && test -x node_modules/.bin/vite
COPY frontend/ ./
ENV VITE_API_BASE_URL=/api \
    VITE_CONTENT_BASE_URL=/content
RUN ./node_modules/.bin/vite build
FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx/default.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
