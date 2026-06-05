"use client";

import { motion } from "framer-motion";
import { Brain, Code, UserCheck, BarChart, Bot } from "lucide-react";
import { cn } from "@/lib/utils";

const agents = [
  { id: "orchestrator", label: "INTERVIEW ORCHESTRATOR", delay: 0 },
  { id: "dsa", label: "DSA ASSESSMENT", delay: 0.2 },
  { id: "aptitude", label: "APTITUDE EVALUATOR", delay: 0.4 },
  { id: "hr", label: "HR BEHAVIORAL", delay: 0.6 },
  { id: "performance", label: "PERFORMANCE ANALYST", delay: 0.8 },
];

export function AuthSidePanel() {
  return (
    <div className="hidden h-screen w-1/2 shrink-0 overflow-hidden border-r border-hairline bg-[#050505] p-12 lg:flex flex-col relative items-center justify-center">
      {/* Background decorations */}
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(94,106,210,0.05),transparent_70%)] pointer-events-none" />

      {/* Network Graph - Unified SVG for Perfect Alignment */}
      <div className="relative z-10 w-full h-[500px] flex items-center justify-center">
        <svg 
          width="500" 
          height="500" 
          viewBox="-250 -250 500 500"
          className="overflow-visible"
        >
          {/* Animated Background Rings */}
          <circle cx="0" cy="0" r="180" fill="none" stroke="rgba(94,106,210,0.05)" strokeWidth="1" strokeDasharray="4 8">
            <animateTransform attributeName="transform" type="rotate" from="0 0 0" to="360 0 0" dur="30s" repeatCount="indefinite" />
          </circle>
          <circle cx="0" cy="0" r="110" fill="none" stroke="rgba(94,106,210,0.08)" strokeWidth="1" strokeDasharray="2 4">
            <animateTransform attributeName="transform" type="rotate" from="0 0 0" to="-360 0 0" dur="20s" repeatCount="indefinite" />
          </circle>

          {/* Main Connection Circle */}
          <circle
            cx="0"
            cy="0"
            r="150"
            fill="none"
            stroke="rgba(94,106,210,0.2)"
            strokeWidth="1.5"
            strokeDasharray="6 6"
          />

          {/* Radial Spokes */}
          {agents.map((_, i) => {
            const angle = (i * 72 - 90) * (Math.PI / 180);
            const x = 150 * Math.cos(angle);
            const y = 150 * Math.sin(angle);
            return (
              <line 
                key={i}
                x1="0" y1="0" x2={x} y2={y} 
                stroke="rgba(94,106,210,0.15)" 
                strokeWidth="1" 
                strokeDasharray="4 4"
              />
            );
          })}

          {/* Agent Nodes */}
          {agents.map((agent, i) => {
            const angle = (i * 72 - 90) * (Math.PI / 180);
            const x = 150 * Math.cos(angle);
            const y = 150 * Math.sin(angle);

            return (
              <g key={agent.id}>
                {/* Node Glow */}
                <circle cx={x} cy={y} r="35" fill="url(#node-gradient)" opacity="0.15" />
                
                {/* ForeignObject for HTML/React content (Avatar + Label) */}
                <foreignObject x={x - 80} y={y - 50} width="160" height="120" className="overflow-visible">
                  <div className="flex flex-col items-center justify-center w-full h-full">
                    <motion.div
                      initial={{ opacity: 0, scale: 0.8 }}
                      animate={{ opacity: 1, scale: 1 }}
                      transition={{ delay: agent.delay, duration: 0.5 }}
                      className="flex flex-col items-center"
                    >
                      <div className="w-14 h-14 rounded-lg border border-hairline bg-black flex items-center justify-center shadow-[0_0_20px_rgba(94,106,210,0.2)] relative group cursor-default">
                        <div className="w-10 h-10 rounded-lg border border-hairline bg-surface-1 flex items-center justify-center group-hover:scale-110 transition-transform">
                          <div className="w-6 h-6 rounded-md bg-primary/20 flex items-center justify-center">
                            <div className="w-2.5 h-2.5 rounded-sm bg-primary animate-pulse shadow-[0_0_8px_#5e6ad2]" />
                          </div>
                        </div>
                      </div>
                      <div className="mt-3 flex flex-col items-center">
                        <span className="text-[10px] font-bold text-ink tracking-[0.2em] whitespace-nowrap uppercase drop-shadow-sm">
                          {agent.label}
                        </span>
                        <div className="h-0.5 w-6 bg-primary/40 mt-1 rounded-full" />
                      </div>
                    </motion.div>
                  </div>
                </foreignObject>
              </g>
            );
          })}

          {/* Center Hub */}
          <circle cx="0" cy="0" r="25" fill="black" stroke="rgba(94,106,210,0.3)" strokeWidth="1" />
          <circle cx="0" cy="0" r="15" fill="rgba(94,106,210,0.1)" stroke="rgba(94,106,210,0.5)" strokeWidth="1" className="animate-pulse" />
          
          <defs>
            <radialGradient id="node-gradient" cx="50%" cy="50%" r="50%" fx="50%" fy="50%">
              <stop offset="0%" stopColor="#5e6ad2" />
              <stop offset="100%" stopColor="transparent" />
            </radialGradient>
          </defs>
        </svg>
      </div>

      <div className="relative z-10 w-full max-w-sm mt-auto mb-8">
        <h2 className="text-display-md text-ink tracking-tight mb-4">
          Experience the future of interview preparation.
        </h2>
        <p className="text-body text-ink-muted mb-6">
          Watch intelligent agents collaborate to create your perfect personalized roadmap.
        </p>
        <ul className="space-y-2">
          {["REAL-TIME AGENT ORCHESTRATION", "INTELLIGENT DSA EVALUATION", "PERSONALIZED RECOMMENDATIONS", "SEAMLESS FEEDBACK GENERATION"].map((item, i) => (
            <li key={i} className="flex items-center gap-2 text-micro font-bold text-ink-muted tracking-wider">
              <div className="w-1.5 h-1.5 rounded-full bg-primary" />
              {item}
            </li>
          ))}
        </ul>
      </div>


    </div>
  );
}
