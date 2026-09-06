import { NextResponse } from 'next/server'
import { loadGraph } from '@/app/lib/graph'

export async function GET() {
  const g = loadGraph()
  return NextResponse.json({ nodes: [...g.nodes.values()], edges: g.edges })
}
