FROM node:{{KAOS_NODE_VERSION}}-slim AS build

ENV PNPM_HOME="/pnpm"
ENV PATH="$PNPM_HOME:$PATH"
RUN corepack enable && corepack prepare pnpm@10.10.0 --activate

WORKDIR /app
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY packages/ packages/
COPY apps/ssr/ apps/ssr/

RUN pnpm install --frozen-lockfile
RUN pnpm --filter @kaos/ssr build

FROM node:{{KAOS_NODE_VERSION}}-slim

WORKDIR /app
COPY --from=build /app/apps/ssr/.output .output

EXPOSE 3000
CMD ["node", ".output/server/index.mjs"]
