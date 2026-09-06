import { NextResponse } from 'next/server'
import { getBacktest } from '@/app/lib/graph'

export async function GET() {
  return NextResponse.json(getBacktest())
}
