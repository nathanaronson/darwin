/**
 * EloChart.tsx — round-robin performance line chart.
 *
 * The previous version plotted Elo, but the orchestrator currently emits
 * `elo_delta=0` on every generation, so the line was always flat and
 * uninformative. Replaced with the new champion's actual round-robin
 * score this gen — wins + 0.5*draws as a percentage of the games it
 * played in the tournament.
 *
 * That number tells the judge two real things:
 *   - >50%  the new champion *dominated* its cohort this generation
 *   - ~50%  a close fight (often baseline retains by tiebreaker)
 *
 * Data source: `game.finished` events bracketed by `generation.started` /
 * `generation.finished`. Score is attributed to the winner-side engine
 * for 1-0 / 0-1, and 0.5 to each side for draws. We rebuild the series
 * from scratch on each render — cheap because the total event count is
 * small (low thousands at most for a multi-gen demo run).
 *
 * @module EloChart
 */

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import type { CubistEvent } from "../api/events";

interface EloChartProps {
  events: CubistEvent[];
}

interface PerfPoint {
  gen: number;
  /** Champion of this generation. */
  champion: string;
  /** Wins + 0.5*draws as percent of games played by the champion. */
  scorePct: number;
  /** Total games the champion played in this gen's round-robin. */
  games: number;
  /** Whether the dashboard saw this gen *promote* (new champion crowned). */
  promoted: boolean;
}

/** Walk the event log once and return one PerfPoint per finished generation. */
function buildPoints(events: CubistEvent[]): PerfPoint[] {
  const points: PerfPoint[] = [];

  // Per-generation accumulators reset at each generation.started boundary.
  let curGen: number | null = null;
  let scoreByEngine = new Map<string, number>();
  let gamesByEngine = new Map<string, number>();

  for (const e of events) {
    if (e.type === "generation.started") {
      curGen = e.number;
      scoreByEngine = new Map();
      gamesByEngine = new Map();
      continue;
    }

    if (e.type === "generation.cancelled") {
      // Cancelled gens never reach `generation.finished`, so we drop the
      // partial accumulators rather than emitting a misleading point.
      curGen = null;
      continue;
    }

    if (e.type === "game.finished" && curGen !== null) {
      const w = e.white;
      const b = e.black;
      gamesByEngine.set(w, (gamesByEngine.get(w) ?? 0) + 1);
      gamesByEngine.set(b, (gamesByEngine.get(b) ?? 0) + 1);
      if (e.result === "1-0") {
        scoreByEngine.set(w, (scoreByEngine.get(w) ?? 0) + 1);
      } else if (e.result === "0-1") {
        scoreByEngine.set(b, (scoreByEngine.get(b) ?? 0) + 1);
      } else {
        // Draw — half a point each. Covers "1/2-1/2" and any other
        // termination that pgn-rules treats as a draw.
        scoreByEngine.set(w, (scoreByEngine.get(w) ?? 0) + 0.5);
        scoreByEngine.set(b, (scoreByEngine.get(b) ?? 0) + 0.5);
      }
      continue;
    }

    if (e.type === "generation.finished" && curGen !== null) {
      const champion = e.new_champion;
      const games = gamesByEngine.get(champion) ?? 0;
      const score = scoreByEngine.get(champion) ?? 0;
      const scorePct = games > 0 ? Math.round((score / games) * 1000) / 10 : 0;
      points.push({
        gen: e.number,
        champion,
        scorePct,
        games,
        promoted: e.promoted,
      });
      curGen = null;
    }
  }

  return points;
}

export default function EloChart({ events }: EloChartProps) {
  const points = buildPoints(events);

  // Y axis: always 0–100 since it's a percentage. A flat 50% line is a
  // decent visual benchmark for "champion was an even match".
  return (
    <div className="bg-gray-800 rounded-lg p-4 flex flex-col">
      <h2 className="text-xs font-semibold tracking-wider text-gray-400 uppercase mb-3">
        Champion Score (round-robin %)
      </h2>

      {points.length === 0 ? (
        <p className="text-gray-500 text-sm italic mt-2">
          Waiting for first generation to finish…
        </p>
      ) : (
        <ResponsiveContainer width="100%" height={200}>
          <LineChart
            data={points}
            margin={{ top: 4, right: 8, left: -10, bottom: 0 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
            <XAxis
              dataKey="gen"
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
              domain={[0, 100]}
              tick={{ fill: "#9ca3af", fontSize: 11 }}
              tickFormatter={(v: number) => `${v}%`}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: "#1f2937",
                border: "1px solid #374151",
                borderRadius: 6,
                color: "#e5e7eb",
                fontSize: 12,
              }}
              formatter={(value: number, _name, item) => {
                const p = item.payload as PerfPoint;
                return [
                  `${value}% (${p.games} games)`,
                  p.promoted ? `${p.champion} (promoted)` : p.champion,
                ];
              }}
              labelFormatter={(label) => `Gen ${label}`}
            />
            <Line
              type="monotone"
              dataKey="scorePct"
              stroke="#3b82f6"
              strokeWidth={2}
              dot={{ fill: "#3b82f6", r: 4 }}
              activeDot={{ r: 6, fill: "#60a5fa" }}
              isAnimationActive={true}
              animationDuration={800}
              animationEasing="ease-out"
            />
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
