import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Dev only. Next blocks cross-origin requests to /_next dev assets, which
  // means HMR dies the moment you open the dashboard on the LAN address
  // instead of localhost — the page loads, then silently stops live-reloading.
  //
  // Subnets, not single addresses: the hotspot hands out a new lease between
  // the hotel and the venue, and hardcoding today's would break at 4am.
  //   172.20.10.*  phone hotspot (what we demo on now)
  //   192.168.4.*  the pinned AP address — laptop hotspot.sh and the Pi
  allowedDevOrigins: ["172.20.10.*", "192.168.4.*"],
};

export default nextConfig;
