'use client'

// Who is signed in, if anyone. Returns `pending` until the first auth event
// lands so the nav can avoid flashing "Sign in" at an already-authenticated
// user on every navigation.
//
// Exposes the whole session, not just the address: the console's account
// chip shows when the token lapses and how the operator got in, and those
// live on the session and the user, not on the email string.

import { useEffect, useState } from 'react'
import type { Session, User } from '@supabase/supabase-js'
import { getSupabase, configured } from './supabase'

export interface SessionState {
  email: string | null
  user: User | null
  session: Session | null
  pending: boolean
  configured: boolean
}

export function useSession(): SessionState {
  const [session, setSession] = useState<Session | null>(null)
  const [pending, setPending] = useState(configured)

  useEffect(() => {
    const sb = getSupabase()
    if (!sb) return

    let live = true
    sb.auth.getSession().then(({ data }) => {
      if (!live) return
      setSession(data.session ?? null)
      setPending(false)
    })

    const { data: sub } = sb.auth.onAuthStateChange((_e, s) => {
      setSession(s ?? null)
      setPending(false)
    })

    return () => { live = false; sub.subscription.unsubscribe() }
  }, [])

  return {
    email: session?.user.email ?? null,
    user: session?.user ?? null,
    session,
    pending,
    configured,
  }
}

export async function signOut() {
  await getSupabase()?.auth.signOut()
}
