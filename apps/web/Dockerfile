FROM node:22-slim AS build
# Public Clerk key is inlined into the client bundle at build time
ARG NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY
ENV NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=$NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY \
    NEXT_PUBLIC_CLERK_SIGN_IN_URL=/sign-in NEXT_PUBLIC_CLERK_SIGN_UP_URL=/sign-up
WORKDIR /repo
COPY packages/design-tokens ./packages/design-tokens
COPY apps/web/package.json apps/web/package-lock.json ./apps/web/
WORKDIR /repo/apps/web
RUN npm ci
COPY apps/web ./
RUN npm run build

FROM node:22-slim
WORKDIR /app
ENV NODE_ENV=production PORT=3000 HOSTNAME=0.0.0.0
COPY --from=build /repo/apps/web/.next/standalone ./
COPY --from=build /repo/apps/web/.next/static ./.next/static
COPY --from=build /repo/apps/web/public ./public
EXPOSE 3000
CMD ["node", "server.js"]
