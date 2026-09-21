/** @type {import('next').NextConfig} */
const nextConfig = {
  // Keep production verification from replacing modules used by a live dev
  // server.  This prevents `next build` from taking the review browser down.
  distDir: process.env.NODE_ENV === "production" ? ".next-production" : ".next-development",
};

export default nextConfig;
