FROM node:24.22.2-alpine

ENV NEXT_TELEMETRY_DISABLED=1

WORKDIR /app
RUN chown node:node /app
USER node

COPY --chown=node:node package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY --chown=node:node . .
# Where the /api/* proxy points; baked into the build. "backend" is the compose service.
ARG BACKEND_URL=http://backend:8000
ENV BACKEND_URL=${BACKEND_URL}
RUN npm run build

EXPOSE 3000
CMD ["npm", "run", "start"]
