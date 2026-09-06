'use client'

// Bottom-right of the console: who is driving it.
//
// A chip — initial, address, plan — that unfolds upward into the account card.
// It sits at the foot of the rail rather than floating on its own, so it shares
// the rail's column and can never land on top of a section: flex pushes it to
// the bottom, and an open section that needs the height simply takes it.
//
// The card is the operator's view of their own account: plan, how and when
// they signed in, when the session lapses, what this console is watching, and
// the keys that drive it. Missing Supabase config is a first-class state here
// too — the chip says "ungated" rather than pretending someone is signed in.

import { useCallback, useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { useSession, signOut } from '../lib/useSession'

const SHORTCUTS: [string, string][] = [
  ['Space / →', 'Next beat'],
  ['←', 'Previous beat'],
  ['↵', 'See new route'],
  ['G', 'Hide node column'],
  ['Esc', 'Restore every failure'],
  ['R', 'Reset the session'],
]

/** The plan lives in auth metadata when the account has one. A fresh
 *  sign-up has none, and the console is the Operate tier's product, so that
 *  is the honest default — marked as such. */
function planOf(meta: Record<string, unknown> | undefined): { name: string; trial: boolean } {
  const p = meta?.plan
  if (typeof p === 'string' && p.trim()) return { name: p, trial: false }
  return { name: 'Operate', trial: true }
}

const when = (iso?: string | null) => {
  if (!iso) return '—'
  const d = new Date(iso)
  return isNaN(d.getTime()) ? '—'
    : d.toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false })
}

/** "in 54 min" / "in 3 h". A token that has already lapsed says so. */
const untilExpiry = (exp?: number) => {
  if (!exp) return '—'
  const s = exp - Math.floor(Date.now() / 1000)
  if (s <= 0) return 'expired'
  if (s < 3600) return `in ${Math.max(1, Math.round(s / 60))} min`
  return `in ${Math.round(s / 3600)} h`
}

export default function AccountChip({ medicines, sessionEvents }: {
  /** Finished drugs this console can root a tree at. */
  medicines: number
  /** Audit-log rows so far — the operator's own activity count. */
  sessionEvents: number
}) {
  const router = useRouter()
  const { email, user, session, pending, configured } = useSession()
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const box = useRef<HTMLDivElement | null>(null)

  // Click-away and Escape both fold it. Escape is stopped here so the
  // console's own Escape (restore all) does not fire while the card is up.
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { e.stopPropagation(); setOpen(false) }
    }
    window.addEventListener('mousedown', onDown)
    window.addEventListener('keydown', onKey, true)
    return () => {
      window.removeEventListener('mousedown', onDown)
      window.removeEventListener('keydown', onKey, true)
    }
  }, [open])

  const leave = useCallback(async () => {
    setBusy(true)
    await signOut()
    // The gate re-runs against a cleared cookie on refresh; replace() alone
    // can hand back a cached console.
    router.replace('/login')
    router.refresh()
  }, [router])

  if (pending) return null

  const plan = planOf(user?.app_metadata as Record<string, unknown> | undefined)
  const who = email ?? (configured ? 'Not signed in' : 'Demo operator')
  const initial = (email ?? 'D')[0].toUpperCase()
  const provider = (user?.app_metadata?.provider as string | undefined) ?? 'email'
  const tone = !configured ? 'warn' : email ? 'ok' : 'dim'

  return (
    <div className="acct" ref={box} data-open={open ? '1' : '0'}>
      {open && (
        <div className="acct-card" role="dialog" aria-label="Account">
          <div className="acct-head">
            <span className="acct-avatar acct-avatar-lg" data-t={tone} aria-hidden>{initial}</span>
            <div className="acct-id">
              <span className="acct-who" title={who}>{who}</span>
              <span className="acct-sub">
                {configured
                  ? email ? `${plan.name}${plan.trial ? ' · trial' : ''} · via ${provider}` : 'Session not established'
                  : 'Console is ungated — Supabase is not configured'}
              </span>
            </div>
          </div>

          <dl className="acct-grid">
            <dt>Plan</dt>
            <dd>
              <span className="tag" data-t={plan.trial ? 'dim' : 'focus'}>{plan.name}</span>
              {' '}<Link href="/#plans" className="acct-link">Change</Link>
            </dd>
            <dt>Member since</dt>
            <dd>{when(user?.created_at)}</dd>
            <dt>Last sign-in</dt>
            <dd>{when(user?.last_sign_in_at)}</dd>
            <dt>Session ends</dt>
            <dd>{configured ? untilExpiry(session?.expires_at) : 'never (ungated)'}</dd>
            <dt>User id</dt>
            <dd className="acct-mono" title={user?.id}>{user?.id ? `${user.id.slice(0, 8)}…` : '—'}</dd>
          </dl>

          <div className="acct-band">
            <div className="acct-stat">
              <b>{medicines}</b>
              <span>medicines</span>
            </div>
            <div className="acct-stat">
              <b>{sessionEvents}</b>
              <span>actions logged</span>
            </div>
            <div className="acct-stat">
              <b>{plan.name === 'Watch' ? 'view' : 'full'}</b>
              <span>access</span>
            </div>
          </div>

          <div className="acct-keys">
            <span className="acct-keys-title">Keys</span>
            {SHORTCUTS.map(([k, what]) => (
              <div className="acct-key" key={k}>
                <kbd>{k}</kbd>
                <span>{what}</span>
              </div>
            ))}
          </div>

          <div className="acct-foot">
            <Link href="/" className="acct-link">Home</Link>
            <Link href="/#plans" className="acct-link">Pricing</Link>
            <span className="spacer" />
            {email ? (
              <button className="acct-out" onClick={leave} disabled={busy}>
                {busy ? 'Signing out…' : 'Sign out'}
              </button>
            ) : configured ? (
              <Link href="/login?next=/app" className="acct-out">Sign in</Link>
            ) : null}
          </div>
        </div>
      )}

      <button
        className="acct-chip"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-haspopup="dialog"
        title={open ? 'Close account' : 'Account'}
      >
        <span className="acct-avatar" data-t={tone} aria-hidden>{initial}</span>
        <span className="acct-chip-who" title={who}>{who}</span>
        <span className="tag" data-t={configured ? (plan.trial ? 'dim' : 'focus') : 'warn'}>
          {configured ? plan.name : 'ungated'}
        </span>
        <span className="acct-chev" aria-hidden>▴</span>
      </button>
    </div>
  )
}
