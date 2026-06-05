"use client";

import Link from "next/link";
import Image from "next/image";
import { cn } from "@/lib/utils";

interface LogoProps {
  className?: string;
  href?: string;
  size?: "sm" | "md" | "lg";
}

export function Logo({ className, href = "/", size = "md" }: LogoProps) {
  const textSizes = {
    sm: "text-headline",
    md: "text-display-md",
    lg: "text-display-lg",
  };

  const iconSizes = {
    sm: 36,
    md: 48,
    lg: 64,
  };

  return (
    <Link href={href} className={cn("flex items-center gap-3 group", className)}>
      <div className="relative flex items-center justify-center">
        <Image
          src="/logo.png"
          alt="InterviewAI Logo"
          width={iconSizes[size]}
          height={iconSizes[size]}
          className="drop-shadow-2xl"
        />
      </div>
      <span className={cn("font-display font-medium text-ink tracking-tight", textSizes[size])}>
        Interview<span className="text-ink-muted">AI</span>
      </span>
    </Link>
  );
}
