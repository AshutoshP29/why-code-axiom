// Every screen's state lives in the URL, so answers can be shared and Back works.

export function whyPath(entityId: string, question: string): string {
  return `/why?${new URLSearchParams({ entity: entityId, q: question })}`
}

export function lineagePath(entityId: string, asOfYear?: number): string {
  const params = new URLSearchParams({ entity: entityId })
  if (asOfYear !== undefined) params.set('asof', String(asOfYear))
  return `/lineage?${params}`
}

export function explorePath(fileId?: string): string {
  return fileId ? `/explore?${new URLSearchParams({ file: fileId })}` : '/explore'
}
