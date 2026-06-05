"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
  LabelList,
} from "recharts";

const SCORE_COLORS = {
  strong: "#22c55e",
  medium: "#5e6ad2",
  weak: "#ff7a3d",
};

type SubjectDatum = {
  subject: string;
  score: number;
  status: string;
};

function scoreStatus(score: number) {
  if (score >= 70) return "strong";
  if (score >= 50) return "medium";
  return "weak";
}

function scoreColor(score: number) {
  return SCORE_COLORS[scoreStatus(score)];
}

function ScoreTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  const score = Number(payload[0].value || 0);
  const status = scoreStatus(score);

  return (
    <div className="rounded-lg border border-hairline bg-surface-1 px-3 py-2 shadow-xl">
      <p className="text-body-sm font-medium text-ink">{label}</p>
      <p className="mt-1 text-caption text-ink-muted">
        Score: <span className="text-ink">{score.toFixed(2)}</span>
      </p>
      <p className="text-caption capitalize" style={{ color: SCORE_COLORS[status] }}>
        {status}
      </p>
    </div>
  );
}

export function SubjectStrengthChart({ data = [] }: { data?: SubjectDatum[] }) {
  const hasData = data.length > 0;

  return (
    <Card className="bg-surface-1 border-hairline">
      <CardHeader>
        <CardTitle className="text-headline text-ink">Subject-wise Performance</CardTitle>
      </CardHeader>
      <CardContent>
        {hasData ? (
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={data} layout="vertical" margin={{ left: 12, right: 56 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#262626" />
            <XAxis 
              type="number" 
              domain={[0, 100]}
              stroke="#999999"
              style={{ fontSize: '12px' }}
            />
            <YAxis 
              dataKey="subject" 
              type="category" 
              stroke="#999999"
              style={{ fontSize: '12px' }}
              width={100}
            />
            <Tooltip content={<ScoreTooltip />} cursor={{ fill: "rgba(255,255,255,0.04)" }} />
            <Bar dataKey="score" radius={[0, 4, 4, 0]} isAnimationActive={false}>
              {data.map((entry) => (
                <Cell key={entry.subject} fill={scoreColor(entry.score)} />
              ))}
              <LabelList
                dataKey="score"
                position="right"
                fill="#ffffff"
                fontSize={12}
                formatter={(value) => `${Number(value || 0).toFixed(0)}`}
              />
            </Bar>
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <div className="flex h-[300px] items-center justify-center text-body-sm text-ink-muted">
            Subject scores appear after your first report.
          </div>
        )}
        <div className="mt-4 flex items-center gap-4 text-caption">
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded-full" style={{ backgroundColor: SCORE_COLORS.strong }} />
            <span className="text-ink-muted">Strong (70+)</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded-full" style={{ backgroundColor: SCORE_COLORS.medium }} />
            <span className="text-ink-muted">Medium (50-70)</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded-full" style={{ backgroundColor: SCORE_COLORS.weak }} />
            <span className="text-ink-muted">Weak (&lt;50)</span>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
