FROM node:22-alpine

WORKDIR /app

# Copy application files
COPY package.json ./
COPY server.js ./
COPY lib/ ./lib/
COPY public/ ./public/
COPY bin/ ./bin/

ENV NODE_ENV=production
ENV PORT=4567

EXPOSE 4567

CMD ["node", "server.js"]
