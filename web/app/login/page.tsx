'use client'

// Email + password, both directions on one form.
//
// Not a magic link: magic links depend on mail delivery and a configured
// redirect origin, and the demo runs off a hotspot whose address changes
// between the hotel and the venue. A password round-trips against Supabase
// alone.

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import Image from 'next/image'
import Link from 'next/link'
import { getSupabase, configured } from '../lib/supabase'

type Mode = 'in' | 'up'

export default function LoginPage() {
  const router = useRouter()
  const [mode, setMode] = useState<Mode>('in')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    const sb = getSupabase()
    if (!sb) return

    setBusy(true); setError(null); setNotice(null)
    const res = mode === 'in'
      ? await sb.auth.signInWithPassword({ email, password })
      : await sb.auth.signUp({ email, password })
    setBusy(false)

    if (res.error) { setError(res.error.message); return }
    // A project with email confirmation on returns a user but no session.
    // Saying "check your inbox" beats bouncing to a console as a signed-out user.
    if (!res.data.session) { setNotice('Check your inbox to confirm the address.'); return }
    router.push('/app')
  }

  return (
    <main className="auth">
      <form className="auth-card" onSubmit={submit}>
        <Link className="auth-mark" href="/">
          <Image src="/ripple-mark.png" alt="" width={20} height={20} />
          <span>RIPPLE</span>
        </Link>

        <h1>{mode === 'in' ? 'Sign in' : 'Create an account'}</h1>
        <p className="auth-sub">Operator access to the sourcing console.</p>

        {!configured && (
          <p className="auth-flag">
            Supabase is not configured in this environment. Set
            <code> NEXT_PUBLIC_SUPABASE_URL </code> and
            <code> NEXT_PUBLIC_SUPABASE_ANON_KEY </code> to enable sign-in — the
            console itself needs no account.
          </p>
        )}

        <label className="auth-field">
          <span>Email</span>
          <input type="email" value={email} required autoComplete="email"
            disabled={!configured || busy}
            onChange={(e) => setEmail(e.target.value)} />
        </label>

        <label className="auth-field">
          <span>Password</span>
          <input type="password" value={password} required minLength={6}
            autoComplete={mode === 'in' ? 'current-password' : 'new-password'}
            disabled={!configured || busy}
            onChange={(e) => setPassword(e.target.value)} />
        </label>

        {error && <p className="auth-err">{error}</p>}
        {notice && <p className="auth-note">{notice}</p>}

        <button className="btn btn-primary auth-go" type="submit" disabled={!configured || busy}>
          {busy ? 'Working…' : mode === 'in' ? 'Sign in' : 'Create account'}
        </button>

        <button className="auth-swap" type="button"
          onClick={() => { setMode(mode === 'in' ? 'up' : 'in'); setError(null); setNotice(null) }}>
          {mode === 'in' ? 'No account? Create one' : 'Already have an account? Sign in'}
        </button>

        <Link className="auth-skip" href="/app">Skip — open the console read-only →</Link>
      </form>
    </main>
  )
}
