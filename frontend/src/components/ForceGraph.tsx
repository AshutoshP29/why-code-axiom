import {
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
  type ForceLink,
  type Simulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from 'd3-force'
import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import type { GraphViewEdge, GraphViewNode } from '../api/types'
import { CANVAS_BG, EDGE_ACTIVE, EDGE_COLOR, FRESH_COLOR, KIND_STYLE } from '../lib/graph-kinds'
import { useLatest } from '../lib/hooks'

/** Above this many nodes the drawing is a canvas; SVG below it, where each node is a button. */
export const CANVAS_ABOVE = 300

// jsdom has no layout or canvas: tests run a short layout at once instead of animating it.
const ANIMATE = typeof navigator === 'undefined' || !/jsdom/i.test(navigator.userAgent)
const LABEL_TEXT = '#a7afbd' // --color-muted
const SELECTED_RING = '#e8eaed' // --color-ink
const MIN_ZOOM = 0.08
const MAX_ZOOM = 8
const LABELS_FROM_ZOOM = 1.4 // every label shows once zoomed in this far
const PRE_TICKS = 130 // d3's alpha falls from 1 to about 0.05 in this many ticks
const SETTLE_ALPHA = 0.05
const LIVE_ALPHA = 0.15 // gentle: a few new nodes should not shake the whole drawing

interface SimNode extends SimulationNodeDatum {
  id: string
  data: GraphViewNode
}

interface SimLink extends SimulationLinkDatum<SimNode> {
  type: string
}

interface Transform {
  x: number
  y: number
  k: number
}

interface Drag {
  mode: 'node' | 'pan'
  id: string | null
  startX: number
  startY: number
  origin: Transform
  moved: boolean
}

interface Placed {
  id: string
  data: GraphViewNode
  x: number
  y: number
}

/** One frame of the layout, as plain values React can render. */
interface Scene {
  t: Transform
  nodes: Placed[]
  links: { key: string; a: Placed; b: Placed }[]
}

const EMPTY_SCENE: Scene = { t: { x: 0, y: 0, k: 1 }, nodes: [], links: [] }

const end = (side: SimNode | string | number): SimNode | null => (typeof side === 'object' ? side : null)
const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))
const linksOf = (sim: Simulation<SimNode, SimLink>) => (sim.force('link') as ForceLink<SimNode, SimLink>).links()

function snapshot(sim: Simulation<SimNode, SimLink>, t: Transform): Scene {
  const placed = new Map<string, Placed>()
  for (const n of sim.nodes()) {
    if (n.x !== undefined && n.y !== undefined) placed.set(n.id, { id: n.id, data: n.data, x: n.x, y: n.y })
  }
  const links: Scene['links'] = []
  for (const l of linksOf(sim)) {
    const a = placed.get(end(l.source)?.id ?? '')
    const b = placed.get(end(l.target)?.id ?? '')
    if (a && b) links.push({ key: `${a.id}|${b.id}|${l.type}`, a, b })
  }
  return { t: { ...t }, nodes: [...placed.values()], links }
}

/** The transform that shows every placed node in a w x h box. */
function fitted(sim: Simulation<SimNode, SimLink>, w: number, h: number): Transform | null {
  const placed = sim.nodes().filter((n) => n.x !== undefined && n.y !== undefined)
  if (placed.length === 0) return null
  const xs = placed.map((n) => n.x as number)
  const ys = placed.map((n) => n.y as number)
  const [minX, maxX, minY, maxY] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)]
  const pad = 40
  const k = clamp(Math.min(w / (maxX - minX + 2 * pad), h / (maxY - minY + 2 * pad)), MIN_ZOOM, 2)
  return { k, x: w / 2 - (k * (minX + maxX)) / 2, y: h / 2 - (k * (minY + maxY)) / 2 }
}

function paintCanvas(
  canvas: HTMLCanvasElement,
  sim: Simulation<SimNode, SimLink>,
  t: Transform,
  { w, h, selectedId, hoverId, fresh }: { w: number; h: number; selectedId: string | null; hoverId: string | null; fresh: ReadonlySet<string> },
) {
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  const dpr = window.devicePixelRatio || 1
  if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
    canvas.width = Math.round(w * dpr)
    canvas.height = Math.round(h * dpr)
  }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx.fillStyle = CANVAS_BG
  ctx.fillRect(0, 0, w, h)
  ctx.setTransform(dpr * t.k, 0, 0, dpr * t.k, dpr * t.x, dpr * t.y)

  // Links of the selected node last, in teal, so they show above the rest.
  for (const active of [false, true]) {
    ctx.beginPath()
    for (const l of linksOf(sim)) {
      const a = end(l.source)
      const b = end(l.target)
      if (!a || !b || a.x === undefined || b.x === undefined) continue
      if ((selectedId !== null && (a.id === selectedId || b.id === selectedId)) !== active) continue
      ctx.moveTo(a.x, a.y as number)
      ctx.lineTo(b.x, b.y as number)
    }
    ctx.strokeStyle = active ? EDGE_ACTIVE : EDGE_COLOR
    ctx.lineWidth = (active ? 1.5 : 1) / t.k
    ctx.stroke()
  }

  const pulse = 0.55 + 0.45 * Math.sin(performance.now() / 180)
  for (const n of sim.nodes()) {
    if (n.x === undefined || n.y === undefined) continue
    const style = KIND_STYLE[n.data.kind]
    if (fresh.has(n.id)) {
      ctx.beginPath()
      ctx.arc(n.x, n.y, style.radius + 6, 0, 2 * Math.PI)
      ctx.globalAlpha = pulse
      ctx.strokeStyle = FRESH_COLOR
      ctx.lineWidth = 2.5 / t.k
      ctx.stroke()
      ctx.globalAlpha = 1
    }
    ctx.beginPath()
    ctx.arc(n.x, n.y, style.radius, 0, 2 * Math.PI)
    ctx.fillStyle = style.ring ? CANVAS_BG : style.color
    ctx.fill()
    if (style.ring || n.id === selectedId) {
      ctx.strokeStyle = n.id === selectedId ? SELECTED_RING : style.color
      ctx.lineWidth = n.id === selectedId ? 2.5 / t.k : 1.75
      ctx.stroke()
    }
  }

  ctx.font = `${11 / t.k}px Inter, system-ui, sans-serif`
  ctx.lineWidth = 3 / t.k
  ctx.strokeStyle = CANVAS_BG
  ctx.fillStyle = LABEL_TEXT
  for (const n of sim.nodes()) {
    if (n.x === undefined || n.y === undefined) continue
    if (t.k < LABELS_FROM_ZOOM && n.id !== selectedId && n.id !== hoverId) continue
    const x = n.x + KIND_STYLE[n.data.kind].radius + 3 / t.k
    const y = n.y + 4 / t.k
    ctx.strokeText(n.data.label, x, y)
    ctx.fillText(n.data.label, x, y)
  }
}

export function ForceGraph({
  nodes,
  edges,
  layoutKey,
  selectedId,
  fresh,
  onSelect,
  label,
}: {
  nodes: GraphViewNode[]
  edges: GraphViewEdge[]
  layoutKey: string // a new key lays the graph out from scratch and fits it to the view
  selectedId: string | null
  fresh: ReadonlySet<string> // nodes new since the last fetch, highlighted for a moment
  onSelect: (id: string | null) => void
  label: string
}) {
  const boxRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const simRef = useRef<Simulation<SimNode, SimLink> | null>(null)
  const transform = useRef<Transform>({ x: 0, y: 0, k: 1 })
  const drag = useRef<Drag | null>(null)
  const lastKey = useRef<string | null>(null)
  const needsFit = useRef(true)
  const userMoved = useRef(false)
  const raf = useRef(0)
  const [size, setSize] = useState({ w: 800, h: 560 })
  const [scene, setScene] = useState<Scene>(EMPTY_SCENE) // what the SVG draws, copied each frame
  const [hoverId, setHoverId] = useState<string | null>(null)
  const [focusId, setFocusId] = useState<string | null>(null)
  const useCanvas = nodes.length > CANVAS_ABOVE

  // Plain functions behind one ref: the simulation and listeners call the latest ones, which see
  // the latest props, without re-subscribing on every render.
  const engine = useLatest({
    paint() {
      raf.current = 0
      const sim = simRef.current
      if (!sim) return
      if (needsFit.current && !userMoved.current) {
        transform.current = fitted(sim, size.w, size.h) ?? transform.current
        needsFit.current = false
      }
      if (!useCanvas) setScene(snapshot(sim, transform.current))
      else if (canvasRef.current) {
        paintCanvas(canvasRef.current, sim, transform.current, { w: size.w, h: size.h, selectedId, hoverId, fresh })
      }
    },
    /** Draw on the next frame; at once in tests. */
    render() {
      if (!ANIMATE) engine.current.paint()
      else if (!raf.current) raf.current = requestAnimationFrame(() => engine.current.paint())
    },
    fit() {
      const sim = simRef.current
      transform.current = (sim && fitted(sim, size.w, size.h)) ?? transform.current
      engine.current.render()
    },
    zoomAt(px: number, py: number, factor: number) {
      const t = transform.current
      const k = clamp(t.k * factor, MIN_ZOOM, MAX_ZOOM)
      transform.current = { k, x: px - ((px - t.x) * k) / t.k, y: py - ((py - t.y) * k) / t.k }
      userMoved.current = true
      engine.current.render()
    },
  })

  // One simulation for the component's life; the data effect below swaps its nodes.
  useEffect(() => {
    const sim = forceSimulation<SimNode, SimLink>([])
      .force('charge', forceManyBody<SimNode>().strength(-45).distanceMax(420))
      .force(
        'link',
        forceLink<SimNode, SimLink>([])
          .id((d) => d.id)
          .distance(34)
          .strength(0.5),
      )
      .force('collide', forceCollide<SimNode>((d) => KIND_STYLE[d.data.kind].radius + 2))
      .force('x', forceX<SimNode>(0).strength(0.05))
      .force('y', forceY<SimNode>(0).strength(0.05))
      .stop()
    sim.on('tick', () => engine.current.render())
    simRef.current = sim
    return () => {
      sim.stop()
      sim.on('tick', null)
      simRef.current = null
      if (raf.current) cancelAnimationFrame(raf.current)
      raf.current = 0
    }
  }, [engine])

  // New data: keep where known nodes are (a live refresh only adds), start new ones beside a
  // neighbour, and lay out from scratch when the view itself changed.
  useEffect(() => {
    const sim = simRef.current
    if (!sim) return
    const fromScratch = lastKey.current !== layoutKey
    lastKey.current = layoutKey
    const before = new Map(fromScratch ? [] : sim.nodes().map((n) => [n.id, n]))
    const ids = new Set(nodes.map((n) => n.id))
    const shown = edges.filter((e) => ids.has(e.source) && ids.has(e.target))
    const simNodes = nodes.map((data): SimNode => {
      const known = before.get(data.id)
      if (known) return Object.assign(known, { data })
      const partner = shown
        .map((e) => (e.source === data.id ? e.target : e.target === data.id ? e.source : null))
        .map((id) => (id ? before.get(id) : undefined))
        .find((n) => n?.x !== undefined)
      const jitter = () => (Math.random() - 0.5) * 30
      return partner
        ? { id: data.id, data, x: (partner.x as number) + jitter(), y: (partner.y as number) + jitter() }
        : { id: data.id, data }
    })
    sim.nodes(simNodes)
    ;(sim.force('link') as ForceLink<SimNode, SimLink>).links(
      shown.map((e) => ({ source: e.source, target: e.target, type: e.type })),
    )
    if (fromScratch) {
      // Most of the layout before the first frame, so the first view is placed and fitted; the
      // rest settles on screen.
      sim.alpha(1)
      sim.tick(PRE_TICKS)
      needsFit.current = true
      userMoved.current = false
    }
    if (ANIMATE) sim.alpha(fromScratch ? SETTLE_ALPHA : LIVE_ALPHA).restart()
    engine.current.render()
  }, [nodes, edges, layoutKey, engine])

  // Follow the box's size.
  useEffect(() => {
    const box = boxRef.current
    if (!box || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect
      if (width === 0 || height === 0) return
      if (!userMoved.current) needsFit.current = true // still the fitted view: fit the new size
      setSize({ w: Math.round(width), h: Math.round(height) })
    })
    observer.observe(box)
    return () => observer.disconnect()
  }, [])

  // Redraw when what is highlighted changes; on the canvas, keep drawing while new nodes pulse.
  useEffect(() => {
    engine.current.render()
    if (!useCanvas || fresh.size === 0 || !ANIMATE) return
    let id = 0
    const loop = () => {
      engine.current.paint()
      id = requestAnimationFrame(loop)
    }
    id = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(id)
  }, [useCanvas, selectedId, hoverId, fresh, size, engine])

  // Wheel zoom needs a listener that may cancel scrolling, which React's onWheel cannot.
  useEffect(() => {
    const box = boxRef.current
    if (!box) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      const rect = box.getBoundingClientRect()
      engine.current.zoomAt(e.clientX - rect.left, e.clientY - rect.top, Math.exp(-e.deltaY * 0.0015))
    }
    box.addEventListener('wheel', onWheel, { passive: false })
    return () => box.removeEventListener('wheel', onWheel)
  }, [engine])

  function toWorld(e: { clientX: number; clientY: number }) {
    const rect = boxRef.current?.getBoundingClientRect()
    const t = transform.current
    return { x: (e.clientX - (rect?.left ?? 0) - t.x) / t.k, y: (e.clientY - (rect?.top ?? 0) - t.y) / t.k }
  }

  function hit(e: ReactPointerEvent): string | null {
    const el = (e.target as Element).closest?.('[data-node-id]')
    if (el) return el.getAttribute('data-node-id')
    if (!useCanvas) return null
    const p = toWorld(e)
    return simRef.current?.find(p.x, p.y, 6 + 8 / transform.current.k)?.id ?? null
  }

  function onPointerDown(e: ReactPointerEvent<HTMLDivElement>) {
    if (e.button !== 0) return
    const id = hit(e)
    drag.current = {
      mode: id ? 'node' : 'pan',
      id,
      startX: e.clientX,
      startY: e.clientY,
      origin: { ...transform.current },
      moved: false,
    }
    e.currentTarget.setPointerCapture?.(e.pointerId)
  }

  function onPointerMove(e: ReactPointerEvent<HTMLDivElement>) {
    const d = drag.current
    if (!d) {
      if (useCanvas) {
        const id = hit(e)
        if (id !== hoverId) setHoverId(id)
      }
      return
    }
    if (!d.moved && Math.hypot(e.clientX - d.startX, e.clientY - d.startY) < 4) return
    d.moved = true
    if (d.mode === 'pan') {
      transform.current = { ...d.origin, x: d.origin.x + e.clientX - d.startX, y: d.origin.y + e.clientY - d.startY }
      userMoved.current = true
      engine.current.render()
      return
    }
    const node = simRef.current?.nodes().find((n) => n.id === d.id)
    if (!node) return
    const p = toWorld(e)
    node.fx = p.x
    node.fy = p.y
    if (ANIMATE) simRef.current?.alphaTarget(0.3).restart()
    engine.current.render()
  }

  function onPointerUp() {
    const d = drag.current
    drag.current = null
    if (!d) return
    if (d.mode === 'node') {
      const node = simRef.current?.nodes().find((n) => n.id === d.id)
      if (node) {
        node.fx = null
        node.fy = null
      }
      simRef.current?.alphaTarget(0)
    }
    if (!d.moved) onSelect(d.mode === 'node' ? d.id : null)
  }

  const { t, nodes: placed, links } = scene
  const showAllLabels = t.k >= LABELS_FROM_ZOOM
  const toolButton =
    'grid h-8 min-w-8 place-items-center rounded-md border border-line bg-chrome/90 px-2 text-sm font-semibold text-muted hover:text-ink'

  return (
    <div
      ref={boxRef}
      className={`relative h-full w-full touch-none select-none ${useCanvas && hoverId ? 'cursor-pointer' : 'cursor-grab'}`}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      onPointerLeave={() => {
        if (useCanvas && hoverId) setHoverId(null)
      }}
    >
      {useCanvas ? (
        <canvas
          ref={canvasRef}
          role="img"
          aria-label={`${label}. Search above to pick a node.`}
          style={{ width: size.w, height: size.h }}
          className="block"
        />
      ) : (
        <svg width={size.w} height={size.h} role="group" aria-label={label} className="block">
          <g transform={`translate(${t.x},${t.y}) scale(${t.k})`}>
            {links.map(({ key, a, b }) => {
              const active = selectedId !== null && (a.id === selectedId || b.id === selectedId)
              return (
                <line
                  key={key}
                  x1={a.x}
                  y1={a.y}
                  x2={b.x}
                  y2={b.y}
                  stroke={active ? EDGE_ACTIVE : EDGE_COLOR}
                  strokeWidth={(active ? 1.5 : 1) / t.k}
                />
              )
            })}
            {placed.map((n) => {
              const style = KIND_STYLE[n.data.kind]
              const marked = n.id === selectedId || n.id === focusId
              const labelled = showAllLabels || marked || n.id === hoverId
              return (
                <g
                  key={n.id}
                  data-node-id={n.id}
                  transform={`translate(${n.x},${n.y})`}
                  role="button"
                  tabIndex={0}
                  aria-label={`${n.data.label}, ${style.label.toLowerCase()}`}
                  aria-pressed={n.id === selectedId}
                  className="cursor-pointer outline-none"
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      onSelect(n.id)
                    }
                  }}
                  onFocus={() => setFocusId(n.id)}
                  onBlur={() => setFocusId(null)}
                  onMouseEnter={() => setHoverId(n.id)}
                  onMouseLeave={() => setHoverId(null)}
                >
                  {fresh.has(n.id) && (
                    <circle
                      r={style.radius + 6}
                      fill="none"
                      stroke={FRESH_COLOR}
                      strokeWidth={2.5 / t.k}
                      className="animate-pulse"
                      data-fresh
                    />
                  )}
                  {marked && <circle r={style.radius + 3} fill="none" stroke={SELECTED_RING} strokeWidth={2 / t.k} />}
                  <circle
                    r={style.radius}
                    fill={style.ring ? CANVAS_BG : style.color}
                    stroke={style.color}
                    strokeWidth={style.ring ? 1.75 : 0}
                  />
                  {labelled && (
                    <text
                      x={style.radius + 3 / t.k}
                      y={4 / t.k}
                      fontSize={11 / t.k}
                      fill={LABEL_TEXT}
                      stroke={CANVAS_BG}
                      strokeWidth={3 / t.k}
                      paintOrder="stroke"
                    >
                      {n.data.label}
                    </text>
                  )}
                </g>
              )
            })}
          </g>
        </svg>
      )}
      <div className="absolute top-2 right-2 flex gap-1" onPointerDown={(e) => e.stopPropagation()}>
        <button
          type="button"
          aria-label="Zoom in"
          title="Zoom in"
          className={toolButton}
          onClick={() => engine.current.zoomAt(size.w / 2, size.h / 2, 1.4)}
        >
          +
        </button>
        <button
          type="button"
          aria-label="Zoom out"
          title="Zoom out"
          className={toolButton}
          onClick={() => engine.current.zoomAt(size.w / 2, size.h / 2, 1 / 1.4)}
        >
          −
        </button>
        <button
          type="button"
          aria-label="Fit the graph to the view"
          title="Fit the graph to the view"
          className={toolButton}
          onClick={() => engine.current.fit()}
        >
          Fit
        </button>
      </div>
    </div>
  )
}
