import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server";

// Public: home, auth pages, and Next internals. Everything else requires
// a session. New protected areas are covered automatically.
const isPublicRoute = createRouteMatcher(["/", "/sign-in(.*)", "/sign-up(.*)"]);

export default clerkMiddleware(async (auth, req) => {
  if (!isPublicRoute(req)) {
    await auth.protect();
  }
});

export const config = {
  matcher: ["/((?!_next|.*\\..*).*)", "/(api|trpc)(.*)"],
};
