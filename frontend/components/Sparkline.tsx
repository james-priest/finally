import type { PricePoint } from "@/lib/usePriceStream";

const WIDTH = 80;
const HEIGHT = 24;
const POINTS = 120;

export function Sparkline({ points, up }: { points: PricePoint[]; up: boolean }) {
  const recent = points.slice(-POINTS);
  if (recent.length < 2) return <svg className="h-6 w-full" aria-hidden />;

  const values = recent.map((p) => p.value);
  const min = Math.min(...values);
  const range = Math.max(...values) - min || 1;
  const step = WIDTH / (POINTS - 1);
  const path = values
    .map((v, i) => `${(i * step).toFixed(1)},${(HEIGHT - 2 - ((v - min) / range) * (HEIGHT - 4)).toFixed(1)}`)
    .join(" ");

  return (
    <svg
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      preserveAspectRatio="none"
      aria-hidden
      className={`h-6 w-full ${up ? "text-up" : "text-down"}`}
    >
      <polyline
        points={path}
        fill="none"
        stroke="currentColor"
        strokeWidth={1.5}
        strokeLinejoin="round"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}
