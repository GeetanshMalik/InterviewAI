"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";

type PerformanceDatum = { label: string; score: number };

export function PerformanceChart({ data = [] }: { data?: PerformanceDatum[] }) {
  const hasData = data.length > 0;

  return (
    <Card className="bg-surface-1 border-hairline">
      <CardHeader>
        <CardTitle className="text-headline text-ink">Performance Over Time</CardTitle>
      </CardHeader>
      <CardContent>
        {hasData ? (
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={data}>
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
            <Line 
              type="monotone" 
              dataKey="score" 
              stroke="#0099ff" 
              strokeWidth={2}
              dot={{ fill: '#0099ff', r: 4 }}
              activeDot={{ r: 6 }}
            />
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <div className="flex h-[300px] items-center justify-center text-body-sm text-ink-muted">
            Complete an interview to see score trends.
          </div>
        )}
      </CardContent>
    </Card>
  );
}
