'use client'

// The only client-side island on the landing page. Split out so the page
// itself stays a server component — the marketing copy is static and there is
// no reason to ship it twice.

import Image from 'next/image'
import Link from 'next/link'
import { useSession, signOut } from '../lib/useSession'

export default function SiteNav() {
  const { email, pending } = useSession()

  return (
    <nav className="nav">
      <Link className="nav-mark" href="/">
        <Image src="/ripple-mark.png" alt="" width={22} height={22} priority />
        <span>RIPPLE</span>
      </Link>

      <div className="nav-links">
        <a href="#how">How it works</a>
        <a href="#plans">Pricing</a>
        <Link href="/app">Console</Link>
      </div>

      <div className="nav-auth">
        {pending ? null : email ? (
          <>
            <span className="nav-who" title={email}>{email}</span>
            <button className="btn btn-ghost" onClick={() => signOut()}>Sign out</button>
          </>
        ) : (
          <Link className="btn btn-ghost" href="/login">Sign in</Link>
        )}
        <Link className="btn btn-primary" href="/app">Open console</Link>
      </div>
    </nav>
  )
}
