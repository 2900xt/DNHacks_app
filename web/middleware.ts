// The auth gate.
//
// Runs on the edge before /app and the data APIs render, so an unauthenticated
// request never reaches the graph at all — this is the real boundary, not the
// login form, which is only the door people knock on.
//
// `getUser()` and not `getSession()`: getSession trusts whatever is in the
// cookie, which the client can forge. getUser revalidates the JWT against the
// auth server. That costs a round trip on every gated request — see the note
// on offline behaviour at the bottom of this file.

import { NextResponse, type NextRequest } from 'next/server'
import { createServerClient } from '@supabase/ssr'

const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL
const SUPABASE_ANON = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY

export async function middleware(request: NextRequest) {
  // Unconfigured deployments fail OPEN. A missing key is an ops mistake, and
  // bricking the console over one — at a venue, minutes before a demo — is a
  // worse outcome than an ungated console. Configured-but-rejected fails
  // CLOSED, which is the case that actually matters.
  if (!SUPABASE_URL || !SUPABASE_ANON) return NextResponse.next()

  // Reassigned inside setAll: refreshed auth cookies have to ride out on the
  // response we actually return, or the session silently stops renewing and
  // the operator gets logged out mid-demo when the access token expires.
  let response = NextResponse.next({ request })

  const supabase = createServerClient(SUPABASE_URL, SUPABASE_ANON, {
    cookies: {
      getAll: () => request.cookies.getAll(),
      setAll: (cookiesToSet) => {
        for (const { name, value } of cookiesToSet) request.cookies.set(name, value)
        response = NextResponse.next({ request })
        for (const { name, value, options } of cookiesToSet) {
          response.cookies.set(name, value, options)
        }
      },
    },
  })

  const { data: { user } } = await supabase.auth.getUser()
  if (user) return response

  // An API caller wants a status code, not a login page it cannot render.
  if (request.nextUrl.pathname.startsWith('/api/')) {
    return NextResponse.json({ error: 'unauthorized' }, { status: 401 })
  }

  // Carry the destination so signing in lands where the operator was headed
  // rather than dumping them on a generic console root.
  const to = request.nextUrl.clone()
  to.pathname = '/login'
  to.search = ''
  to.searchParams.set('next', request.nextUrl.pathname)
  return NextResponse.redirect(to)
}

export const config = {
  // `/api/health` stays open: it is the liveness probe, and a probe that needs
  // credentials cannot tell you the difference between "down" and "locked".
  matcher: ['/app/:path*', '/api/((?!health).*)'],
}
