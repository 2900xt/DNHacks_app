// Supabase browser client.
//
// Deliberately optional. The demo runs off a hotspot at a venue where the
// project's Supabase keys may not be in the environment, and a login screen
// that hard-fails is a login screen that eats the demo. Missing config is a
// first-class state (`configured === false`) that the UI renders as an honest
// notice, not a crash.

import { createBrowserClient } from '@supabase/ssr'
import type { SupabaseClient } from '@supabase/supabase-js'

const url = process.env.NEXT_PUBLIC_SUPABASE_URL
const anon = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY

export const configured = Boolean(url && anon)

// One client per tab. `createBrowserClient` is cheap but the auth listener it
// installs is not — a client per render leaks a subscription per render.
let client: SupabaseClient | null = null

export function getSupabase(): SupabaseClient | null {
  if (!configured) return null
  if (!client) client = createBrowserClient(url!, anon!)
  return client
}
