// The door. The lock itself is middleware.ts — this page only collects
// credentials and gets out of the way.

import { Suspense } from 'react'
import LoginForm from './LoginForm'

// useSearchParams needs a Suspense boundary or it opts the whole route into
// dynamic rendering. The fallback is the card's own frame so the box does not
// pop into existence a beat after the background.
export default function LoginPage() {
  return (
    <main className="auth">
      <Suspense fallback={<div className="auth-card auth-card-ghost" />}>
        <LoginForm />
      </Suspense>
    </main>
  )
}
