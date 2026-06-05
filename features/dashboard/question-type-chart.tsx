"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

const CATEGORY_COLORS: Record<string, string> = {
  DSA: "#4596f0",
  Aptitude: "#6a4cf5",
  Technical: "#d44df0",
  HR: "#ff7a3d",
};

type DistributionDatum = {
  name: string;
  value: number;
};

function colorFor(name: string) {
  return CATEGORY_COLORS[name] || "#5e6ad2";
}

function percentFor(value: number, total: number) {
  if (!total) return 0;
  return (value / total) * 100;
}

function DistributionTooltip({ active, payload, total }: any) {
  if (!active || !payload?.length) return null;
  const item = payload[0].payload as DistributionDatum;
  const percent = percentFor(item.value, total);

  return (
    <div className="rounded-lg border border-hairline bg-surface-1 px-3 py-2 shadow-xl">
      <p className="text-body-sm font-medium text-ink">{item.name}</p>
      <p className="mt-1 text-caption text-ink-muted">
        Questions: <span className="text-ink">{item.value}</span>
      </p>
      <p className="text-caption text-ink-muted">
        Share: <span className="text-ink">{percent.toFixed(1)}%</span>
      </p>
    </div>
  );
}

function SliceLabel({ name, value, percent, x, y, cx }: any) {
  return (
    <text
      x={x}
      y={y}
      fill={colorFor(name)}
      textAnchor={x > cx ? "start" : "end"}
      dominantBaseline="central"
      className="text-caption font-medium"
    >
      {name} {value} ({((percent || 0) * 100).toFixed(0)}%)
    </text>
  );
}

export function QuestionTypeChart({ data = [] }: { data?: DistributionDatum[] }) {
  const chartData = data.filter((item) => item.value > 0);
  const hasData = chartData.length > 0;
  const total = chartData.reduce((sum, item) => sum + item.value, 0);

  return (
    <Card className="bg-surface-1 border-hairline">
      <CardHeader>
        <CardTitle className="text-headline text-ink">Practice Distribution</CardTitle>
      </CardHeader>
      <CardContent>
        {hasData ? (
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_220px] xl:items-center">
            <ResponsiveContainer width="100%" height={320}>
              <PieChart margin={{ top: 12, right: 52, bottom: 12, left: 52 }}>
                <Pie
                  data={chartData}
                  cx="50%"
                  cy="50%"
                  labelLine={{ stroke: "#666", strokeWidth: 1 }}
                  label={<SliceLabel />}
                  outerRadius={82}
                  innerRadius={28}
                  dataKey="value"
                  nameKey="name"
                  isAnimationActive={false}
                >
                  {chartData.map((entry) => (
                    <Cell key={entry.name} fill={colorFor(entry.name)} stroke="#ffffff" strokeWidth={1} />
                  ))}
                </Pie>
                <Tooltip content={<DistributionTooltip total={total} />} />
              </PieChart>
            </ResponsiveContainer>

            <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-1">
              {chartData.map((item) => {
                const percent = percentFor(item.value, total);
                return (
                  <div key={item.name} className="rounded-md border border-hairline bg-surface-2 p-3">
                    <div className="flex items-center justify-between gap-3">
                      <div className="flex min-w-0 items-center gap-2">
                        <span
                          className="h-3 w-3 shrink-0 rounded-full"
                          style={{ backgroundColor: colorFor(item.name) }}
                        />
                        <span className="truncate text-body-sm font-medium text-ink">{item.name}</span>
                      </div>
                      <span className="text-body-sm text-ink">{item.value}</span>
                    </div>
                    <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-black/30">
                      <div
                        className="h-full rounded-full"
                        style={{
                          width: `${percent}%`,
                          backgroundColor: colorFor(item.name),
                        }}
                      />
                    </div>
                    <p className="mt-1 text-caption text-ink-muted">{percent.toFixed(1)}%</p>
                  </div>
                );
              })}
            </div>
          </div>
        ) : (
          <div className="flex h-[300px] items-center justify-center text-body-sm text-ink-muted">
            Practice and interview question mix will appear here.
          </div>
        )}
      </CardContent>
    </Card>
  );
}
