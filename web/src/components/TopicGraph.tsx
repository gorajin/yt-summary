import { useEffect, useRef } from 'react'
import * as d3 from 'd3'
import type { TopicData, ConnectionData } from '../services/api'

interface TopicGraphProps {
  topics: TopicData[]
  connections: ConnectionData[]
  onSelectTopic: (topic: TopicData) => void
}

interface NodeDatum extends d3.SimulationNodeDatum {
  id: string
  topic: TopicData
}

interface LinkDatum extends d3.SimulationLinkDatum<NodeDatum> {
  relationship: string
}

export default function TopicGraph({ topics, connections, onSelectTopic }: TopicGraphProps) {
  const svgRef = useRef<SVGSVGElement>(null)

  useEffect(() => {
    if (!svgRef.current || topics.length === 0) return

    const svg = d3.select(svgRef.current)
    svg.selectAll('*').remove()

    const width = svgRef.current.clientWidth
    const height = svgRef.current.clientHeight

    // Build nodes and links
    const topicNames = new Set(topics.map((t) => t.name))
    const nodes: NodeDatum[] = topics.map((t) => ({
      id: t.name,
      topic: t,
    }))

    const links: LinkDatum[] = connections
      .filter((c) => topicNames.has(c.from) && topicNames.has(c.to))
      .map((c) => ({
        source: c.from,
        target: c.to,
        relationship: c.relationship,
      }))

    // Color scale based on importance
    const colorScale = d3
      .scaleLinear<string>()
      .domain([1, 5, 10])
      .range(['#22c55e', '#a855f7', '#ef4444'])

    // Force simulation
    const simulation = d3
      .forceSimulation(nodes)
      .force(
        'link',
        d3
          .forceLink<NodeDatum, LinkDatum>(links)
          .id((d) => d.id)
          .distance(120)
      )
      .force('charge', d3.forceManyBody().strength(-300))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collision', d3.forceCollide().radius(40))

    // Zoom behavior
    const g = svg.append('g')
    svg.call(
      d3.zoom<SVGSVGElement, unknown>().scaleExtent([0.3, 3]).on('zoom', (event) => {
        g.attr('transform', event.transform)
      }) as never
    )

    // Links
    const link = g
      .append('g')
      .selectAll('line')
      .data(links)
      .join('line')
      .attr('stroke', '#d1d5db')
      .attr('stroke-width', 1.5)
      .attr('stroke-opacity', 0.6)

    // Link labels
    const linkLabel = g
      .append('g')
      .selectAll('text')
      .data(links)
      .join('text')
      .text((d) => d.relationship)
      .attr('font-size', '9px')
      .attr('fill', '#9ca3af')
      .attr('text-anchor', 'middle')

    // Nodes
    const node = g
      .append('g')
      .selectAll('g')
      .data(nodes)
      .join('g')
      .attr('cursor', 'pointer')
      .on('click', (_event, d) => onSelectTopic(d.topic))
      .call(
        d3
          .drag<SVGGElement, NodeDatum>()
          .on('start', (event, d) => {
            if (!event.active) simulation.alphaTarget(0.3).restart()
            d.fx = d.x
            d.fy = d.y
          })
          .on('drag', (event, d) => {
            d.fx = event.x
            d.fy = event.y
          })
          .on('end', (event, d) => {
            if (!event.active) simulation.alphaTarget(0)
            d.fx = null
            d.fy = null
          })
      )

    node
      .append('circle')
      .attr('r', (d) => 8 + (d.topic.importance ?? 5) * 1.5)
      .attr('fill', (d) => colorScale(d.topic.importance ?? 5))
      .attr('fill-opacity', 0.85)
      .attr('stroke', '#fff')
      .attr('stroke-width', 2)

    node
      .append('text')
      .text((d) => d.id)
      .attr('dy', (d) => -(12 + (d.topic.importance ?? 5) * 1.5))
      .attr('text-anchor', 'middle')
      .attr('font-size', '11px')
      .attr('font-weight', '600')
      .attr('fill', '#374151')

    // Tick
    simulation.on('tick', () => {
      link
        .attr('x1', (d) => (d.source as NodeDatum).x!)
        .attr('y1', (d) => (d.source as NodeDatum).y!)
        .attr('x2', (d) => (d.target as NodeDatum).x!)
        .attr('y2', (d) => (d.target as NodeDatum).y!)

      linkLabel
        .attr('x', (d) => ((d.source as NodeDatum).x! + (d.target as NodeDatum).x!) / 2)
        .attr('y', (d) => ((d.source as NodeDatum).y! + (d.target as NodeDatum).y!) / 2)

      node.attr('transform', (d) => `translate(${d.x},${d.y})`)
    })

    return () => {
      simulation.stop()
    }
  }, [topics, connections, onSelectTopic])

  return <svg ref={svgRef} className="topic-graph" />
}
