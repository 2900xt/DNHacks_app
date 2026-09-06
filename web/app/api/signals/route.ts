import { NextResponse } from 'next/server'
import { getSignals } from '@/app/lib/graph'

export async function GET(req: Request) {
  const since = new URL(req.url).searchParams.get('since') ?? undefined
  return NextResponse.json(getSignals(since))
}
