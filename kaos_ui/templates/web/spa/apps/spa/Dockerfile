FROM node:{{KAOS_NODE_VERSION}}-slim AS build

ENV PNPM_HOME="/pnpm"
ENV PATH="$PNPM_HOME:$PATH"
RUN corepack enable && corepack prepare pnpm@10.10.0 --activate

WORKDIR /app
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY packages/ packages/
COPY apps/spa/ apps/spa/

RUN pnpm install --frozen-lockfile
RUN pnpm --filter @kaos/spa build

FROM caddy:2-alpine
COPY apps/spa/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /app/apps/spa/dist /srv
