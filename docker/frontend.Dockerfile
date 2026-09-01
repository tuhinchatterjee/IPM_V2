# =============================================================================
# IPM frontend — the Next.js interface
# =============================================================================
#
# Build with the FRONTEND folder as the context (docker-compose.yml does this):
#
#     docker build -f docker/frontend.Dockerfile -t ipm-frontend ./frontend
#
# Node.js and every npm package live inside the image, so nothing has to be
# installed on the host machine.
#
# Three stages, so the image that actually runs contains no build tooling:
#
#   deps     installs npm packages
#   builder  compiles the application
#   runner   runs it — Node plus the compiled output, nothing else

# Parameterised so a machine behind a TLS-inspecting corporate proxy can point
# the build at a base image that already trusts its certificate authority.
# Leave it alone and the standard public image is used.
ARG NODE_IMAGE=node:22-alpine

# ---------------------------------------------------------------- 1. packages
FROM ${NODE_IMAGE} AS deps
WORKDIR /app
# Only the lockfile, so this layer is cached until a dependency actually changes.
COPY package.json package-lock.json ./
RUN npm ci

# ----------------------------------------------------------------- 2. compile
FROM ${NODE_IMAGE} AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Where the BROWSER should send API calls.
#
# Empty on purpose. An empty value makes the API client call the page's own
# origin — /api/v1/... — which Next.js then forwards to the backend container
# (see the rewrite in next.config.ts). The alternative, baking in
# http://localhost:8000, would hard-code an address into the JavaScript at build
# time and break the moment the application is opened as anything other than
# "localhost".
ARG NEXT_PUBLIC_API_URL=""
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}

# Where the Next.js SERVER forwards those calls to.
#
# This is a build argument rather than only a run-time variable because Next.js
# resolves rewrite destinations during `next build` and stores them in the build
# output. Setting it at run time alone would leave the compiled application
# still pointing at the default. It defaults to the Docker service name, which
# is what docker-compose.yml calls the backend.
ARG BACKEND_INTERNAL_URL=http://backend:8000
ENV BACKEND_INTERNAL_URL=${BACKEND_INTERNAL_URL}

ENV NEXT_TELEMETRY_DISABLED=1

RUN npm run build

# --------------------------------------------------------------------- 3. run
FROM ${NODE_IMAGE} AS runner
WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# `output: "standalone"` in next.config.ts produces a self-contained server with
# only the modules it actually uses, so the running image needs no npm install
# and is a fraction of the size. Static assets are copied alongside it, as the
# Next.js self-hosting guide describes.
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static

# Run as the unprivileged user the Node image already provides.
USER node

EXPOSE 3000

# HOSTNAME=0.0.0.0 above is what makes the server listen on every interface
# rather than only inside the container.
CMD ["node", "server.js"]
