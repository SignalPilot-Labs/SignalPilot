FROM node:22-alpine AS builder
WORKDIR /app

ARG WORKSPACES_API_URL=http://workspaces-api:3400

ENV WORKSPACES_API_URL=$WORKSPACES_API_URL

# Copy only the workspaces/web package files first for layer caching
COPY workspaces/web/package.json workspaces/web/package-lock.json* ./
RUN npm install --prefer-offline

# Copy the rest of the workspaces/web source
COPY workspaces/web/ ./

RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production

COPY --from=builder /app/.next ./.next
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./
RUN mkdir -p /app/public

# Entrypoint: wait up to 30s for shared volume to contain the local API key
RUN printf '#!/bin/sh\ni=0\nwhile [ ! -f /shared/local_api_key ] && [ "$i" -lt 30 ]; do\n  sleep 1\n  i=$((i+1))\ndone\nif [ -f /shared/local_api_key ]; then\n  export SP_LOCAL_API_KEY="$(cat /shared/local_api_key)"\nfi\nexec npm start -- --port 3500\n' > /app/entrypoint.sh && chmod +x /app/entrypoint.sh

EXPOSE 3500
CMD ["/app/entrypoint.sh"]
