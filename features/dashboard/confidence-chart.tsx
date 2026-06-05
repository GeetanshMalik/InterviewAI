"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Area, AreaChart } from "recharts";

type ConfidenceDatum = { label: string; confidence: number };

export function ConfidenceChart({ data = [] }: { data?: ConfidenceDatum[] }) {
  const hasData = data.length > 0;

  return (
    <Card className="bg-surface-1 border-hairline">
      <CardHeader>
        <CardTitle className="text-headline text-ink">Confidence Trend</CardTitle>
      </CardHeader>
      <CardContent>
        {hasData ? (
          <ResponsiveContainer width="100%" height={300}>
            <AreaChart data={data}>
            <defs>
              <linearGradient id="confidenceGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#22c55e" stopOpacity={0.3}/>
                <stop offset="95%" stopColor="#22c55e" stopOpacity={0}/>
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#262626" />
            <XAxis 
              dataKey="label"
              stroke="#999999"
              style={{ fontSize: '12px' }}
            />
            <YAxis 
              stroke="#999999"
              domain={[0, 100]}
              allowDecimals={false}
              style={{ fontSize: '12px' }}
            />
            <Tooltip 
              contentStyle={{ 
                backgroundColor: '#141414', 
                border: '1px solid #262626',
                borderRadius: '8px',
                color: '#ffffff'
              }}
            />
            <Area 
              type="monotone" 
              dataKey="confidence" 
              stroke="#22c55e" 
              strokeWidth={2}
              fill="url(#confidenceGradient)"
            />
            </AreaChart>
          </ResponsiveContainer>
        ) : (
          <div className="flex h-[300px] items-center justify-center text-body-sm text-ink-muted">
            Confidence appears after report feedback is generated.
          </div>
        )}
      </CardContent>
    </Card>
  );
}
