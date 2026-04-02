FROM node:22-alpine

WORKDIR /app

# Install wget for healthcheck
RUN apk add --no-cache wget

# Install dependencies
COPY package.json package-lock.json* ./
RUN npm install --production

# Copy application
COPY server.js ./
COPY public/ ./public/
COPY scripts/ ./scripts/

# Non-root user for security
RUN addgroup -S spgw && adduser -S spgw -G spgw
RUN mkdir -p /app/data && chown -R spgw:spgw /app/data
USER spgw

# Credentials stored in a volume
ENV CREDENTIALS_FILE=/app/data/credentials.json
ENV NODE_ENV=production

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=10s \
  CMD wget --no-verbose --tries=1 --spider http://localhost:8080/health || exit 1

CMD ["node", "server.js"]
