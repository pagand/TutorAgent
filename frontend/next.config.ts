import type { NextConfig } from 'next'

const nextConfig: NextConfig = {
  output: 'export',
  trailingSlash: true,
  // Allow LAN access in dev (e.g. testing on another machine on the same network).
  // No effect on the static production export.
  allowedDevOrigins: ['192.168.1.136'],
}

export default nextConfig
