import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server";

// Everything needs a signed-in user except the auth pages and the health check.
const isPublic = createRouteMatcher(["/sign-in(.*)", "/sign-up(.*)", "/api/health"]);

export default clerkMiddleware(async (auth, req) => {
  if (!isPublic(req)) await auth.protect();
});

export const config = {
  matcher: [
    // Skip Next internals and static files (including the MapLibre worker in /vendor).
    "/((?!_next|vendor|brand|[^?]*\\.(?:html?|css|js(?!on)|mjs|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|webmanifest)).*)",
    "/(api|files)(.*)",
  ],
};
