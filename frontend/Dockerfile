FROM node:24-alpine

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN chown -R node:node /app
USER node
EXPOSE 5173
# Synchronize the dependency volume after package-lock.json changes.
CMD ["sh", "-c", "npm ci && npm run dev"]
