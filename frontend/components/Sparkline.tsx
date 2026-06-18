"use client";

interface Props {
  data: number[];
  width?: number;
  height?: number;
  color?: string;
  fill?: string;
  domain?: [number, number];
  zeroLine?: boolean;
}

export default function Sparkline({
  data,
  width = 240,
  height = 40,
  color = "#38bdf8",
  fill = "rgba(56,189,248,0.15)",
  domain,
  zeroLine = false,
}: Props) {
  // Drop non-finite samples (NaN/Infinity from a dropped telemetry frame):
  // a single bad value would otherwise poison Math.min/max and render an
  // empty/broken chart.
  const clean = data.filter(Number.isFinite);
  if (clean.length < 2) {
    return (
      <svg width={width} height={height} className="block">
        <line
          x1={0}
          x2={width}
          y1={height / 2}
          y2={height / 2}
          stroke="#27272a"
          strokeDasharray="2 2"
        />
      </svg>
    );
  }

  const lo = domain ? domain[0] : Math.min(...clean);
  const hi = domain ? domain[1] : Math.max(...clean);
  const span = hi - lo || 1;
  const stepX = width / (clean.length - 1);
  const toY = (v: number) => height - ((v - lo) / span) * (height - 4) - 2;

  const points = clean.map((v, i) => `${i * stepX},${toY(v)}`).join(" ");
  const area = `0,${height} ${points} ${width},${height}`;
  const yZero = zeroLine ? toY(0) : null;

  return (
    <svg width={width} height={height} className="block">
      {yZero !== null && (
        <line x1={0} x2={width} y1={yZero} y2={yZero} stroke="#27272a" strokeDasharray="2 2" />
      )}
      <polygon points={area} fill={fill} />
      <polyline points={points} fill="none" stroke={color} strokeWidth={1.5} />
    </svg>
  );
}
