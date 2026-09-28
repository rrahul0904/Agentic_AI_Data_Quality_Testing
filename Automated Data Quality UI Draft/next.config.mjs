/** @type {import('next').NextConfig} */
const nextConfig = {
  // Keep production verification from replacing modules used by a live dev
  // server.  This prevents `next build` from taking the review browser down.
  // A caller can additionally choose an isolated output directory to build
  // and smoke-test a candidate while a production server keeps serving its
  // current artifact. Never point this at the active directory during a build.
  distDir: process.env.ADE_NEXT_DIST_DIR || (process.env.NODE_ENV === "production" ? ".next-production" : ".next-development"),
};

export default nextConfig;
