import { NextResponse } from 'next/server'
import { counts } from '@/app/lib/graph'

/** How anyone checks the data actually loaded, at 3am or from the Vercel URL. */
export async function GET() {
  return NextResponse.json({ ok: true, counts: counts() })
}
