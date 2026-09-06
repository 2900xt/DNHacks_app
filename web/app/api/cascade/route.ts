import { NextResponse } from 'next/server'
import { cascade } from '@/app/lib/graph'

/** Beat 4. POST { nodeId } -> { affected, rule, firedBy }. */
export async function POST(req: Request) {
  const { nodeId } = await req.json()
  if (!nodeId) {
    return NextResponse.json({ error: 'nodeId required' }, { status: 400 })
  }
  return NextResponse.json(cascade(nodeId))
}
