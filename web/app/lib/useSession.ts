'use client'

// Who is signed in, if anyone. Returns `pending` until the first auth event
// lands so the nav can avoid flashing "Sign in" at an already-authenticated
// user on every navigation.

import { useEffect, useState } from 'react'
import { getSupabase, configured } from './supabase'

export interface SessionState {
  email: string | null
  pending: boolean
  configured: boolean
}

export function useSession(): SessionState {
  const [email, setEmail] = useState<string | null>(null)
  const [pending, setPending] = useState(configured)

  useEffect(() => {
    const sb = getSupabase()
    if (!sb) return

    let live = true
    sb.auth.getSession().then(({ data }) => {
      if (!live) return
      setEmail(data.session?.user.email ?? null)
      setPending(false)
    })

    const { data: sub } = sb.auth.onAuthStateChange((_e, session) => {
      setEmail(session?.user.email ?? null)
      setPending(false)
    })

    return () => { live = false; sub.subscription.unsubscribe() }
  }, [])

  return { email, pending, configured }
}

export async function signOut() {
  await getSupabase()?.auth.signOut()
}
