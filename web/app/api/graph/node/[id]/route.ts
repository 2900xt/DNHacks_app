import { NextResponse } from 'next/server'
import { getNode } from '@/app/lib/graph'

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params
  const result = getNode(decodeURIComponent(id))
  if (!result) return NextResponse.json({ error: 'not found' }, { status: 404 })
  return NextResponse.json(result)
}
