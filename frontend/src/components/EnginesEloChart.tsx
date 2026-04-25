/**
 * EnginesEloChart.tsx — Elo trajectory of every engine that's played.
 *
 * Walks every `generation.finished` event, pulls its `ratings` dict
 * (post-tournament Elo for each engine in the cohort), and renders one
 * Recharts line per engine. An engine that only played one generation
 * shows a single dot at that gen; one that's stuck around (baseline-v0,
 * repeat incumbents) gets a multi-point line. We do NOT forward-fill
 * Elo across generations the engine sat out — a flat horizontal line
 * implies the engine kept playing at that rating, which is misleading.
 * `connectNulls={true}` joins the dots an engine actually played in.
 *
 * Top-N filter: ranked by the engine's *peak* Elo across all its
 * appearances, not its current Elo. An engine that crushed gen 1 and
 * never came back deserves to stay on the chart; one whose final Elo
 * happens to be 1500 because it only played one losing game does not
 * outrank it.
 *
 * The single-line champion-Elo view in {@link EloChart} is the
 * "headline" — this chart is the "every contender at once" detail view
 * that lets you see which candidates traded blows.
 *
 * @module EnginesEloChart
 */

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import type { DarwinEvent, GenerationFinished } from "../api/events";

interface EnginesEloChartProps {
  events: DarwinEvent[];
}

/** One row of the data array, with a `gen` index plus an Elo per engine. */
type Row = { gen: number } & Record<string, number | undefined>;

// A small palette of distinct colors. Recharts will recycle if there
// are more engines than colors — fine for a hackathon dashboard.
const COLORS = [
  "#60a5fa", // baseline (blue) — first slot, baseline-v0 always lands here
  "#f97316", // orange
  "#10b981", // emerald
  "#a855f7", // purple
  "#ec4899", // pink
  "#eab308", // yellow
  "#06b6d4", // cyan
  "#f43f5e", // rose
  "#84cc16", // lime
  "#8b5cf6", // violet
];

/** Top-N engines (by peak Elo) shown on the chart. Chart with 30 lines is unreadable. */
const TOP_N = 8;

export default function EnginesEloChart({ events }: EnginesEloChartProps) {
  const finished = events.filter(
    (e): e is GenerationFinished => e.type === "generation.finished",
  );

  // Per-engine series of (gen, elo) points — one entry per gen the
  // engine actually played in. We do NOT forward-fill into gens it
  // sat out. Recharts' `connectNulls` joins the points without
  // implying the engine held that rating in between.
  const series: Record<string, Array<{ gen: number; elo: number }>> = {};
  // baseline-v0 anchors at gen 0 = 1500 (the seed value written by
  // scripts/seed_baseline.py). Every other engine starts the moment
  // it first appears in a `ratings` payload.
  series["baseline-v0"] = [{ gen: 0, elo: 1500 }];

  for (const ev of finished) {
    if (!ev.ratings) continue;
    for (const [name, elo] of Object.entries(ev.ratings)) {
      if (!series[name]) series[name] = [];
      series[name].push({ gen: ev.number, elo });
    }
  }

  // Top-N by peak Elo — engines that performed well at any point stay
  // on the chart even if they stopped being carried forward.
  const peakElo: Array<[string, number]> = Object.entries(series).map(
    ([name, points]) => [name, Math.max(...points.map((p) => p.elo))],
  );
  peakElo.sort((a, b) => b[1] - a[1]);
  const topEngines = new Set(peakElo.slice(0, TOP_N).map(([name]) => name));

  // Build the per-gen rows that Recharts wants. We include every gen
  // where ANY top-N engine has a data point. Engines without a point
  // in that gen leave the field undefined → `connectNulls` skips it.
  const allGens = new Set<number>();
  for (const name of topEngines) {
    for (const p of series[name]) allGens.add(p.gen);
  }
  const sortedGens = Array.from(allGens).sort((a, b) => a - b);

  const data: Row[] = sortedGens.map((gen) => {
    const row: Row = { gen };
    for (const name of topEngines) {
      const point = series[name].find((p) => p.gen === gen);
      if (point) row[name] = point.elo;
    }
    return row;
  });

  // Order legend / Line components: baseline-v0 first (reserves the
  // blue slot), then by peak Elo descending so the leaderboard reads
  // top-to-bottom.
  const peakLookup = new Map(peakElo);
  const engines = Array.from(topEngines).sort((a, b) => {
    if (a === "baseline-v0") return -1;
    if (b === "baseline-v0") return 1;
    return (peakLookup.get(b) ?? 0) - (peakLookup.get(a) ?? 0);
  });

  // Y-axis: ±30 points around the min/max actually present in the
  // (filtered, non-forward-filled) data.
  const eloValues: number[] = [];
  for (const row of data) {
    for (const [k, v] of Object.entries(row)) {
      if (k === "gen") continue;
      if (typeof v === "number") eloValues.push(v);
    }
  }
  const minElo =
    eloValues.length > 0
      ? Math.floor((Math.min(...eloValues) - 30) / 50) * 50
      : 1450;
  const maxElo =
    eloValues.length > 0
      ? Math.ceil((Math.max(...eloValues) + 30) / 50) * 50
      : 1550;

  // Truncate long candidate names in the legend so it wraps nicely.
  const shortName = (name: string) =>
    name.length > 18 ? name.slice(0, 17) + "…" : name;

  return (
    <div className="bg-gray-800 rounded-lg p-4 flex flex-col">
      <h2 className="text-xs font-semibold tracking-wider text-gray-400 uppercase mb-3">
        All Engines Elo (per cohort)
      </h2>

      {finished.length === 0 ? (
        <p className="text-gray-500 text-sm italic mt-2">
          Waiting for first generation to finish…
        </p>
      ) : (
        <ResponsiveContainer width="100%" height={260}>
          <LineChart
            data={data}
            margin={{ top: 4, right: 8, left: -10, bottom: 0 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
            <XAxis
              dataKey="gen"
              type="number"
              domain={["dataMin", "dataMax"]}
              allowDecimals={false}
              tick={{ fill: "#9ca3af", fontSize: 11 }}
              label={{
                value: "Generation",
                position: "insideBottomRight",
                offset: -4,
                fill: "#6b7280",
                fontSize: 10,
              }}
            />
            <YAxis
              domain={[minElo, maxElo]}
              tick={{ fill: "#9ca3af", fontSize: 11 }}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: "#1f2937",
                border: "1px solid #374151",
                borderRadius: 6,
                color: "#e5e7eb",
                fontSize: 11,
              }}
              labelFormatter={(label) => `Gen ${label}`}
            />
            <Legend
              wrapperStyle={{ fontSize: 10, color: "#9ca3af" }}
              formatter={(value: string) => shortName(value)}
            />
            {engines.map((name, i) => (
              <Line
                key={name}
                type="linear"
                dataKey={name}
                name={name}
                stroke={COLORS[i % COLORS.length]}
                strokeWidth={name === "baseline-v0" ? 2.5 : 1.5}
                // Engines only have a point at gens they actually
                // played — `connectNulls` joins those points without
                // implying they held that rating in between.
                connectNulls={true}
                dot={{ r: 3 }}
                activeDot={{ r: 5 }}
                isAnimationActive={true}
                animationDuration={500}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
