import { ReactNode } from "react";
import { Navbar } from "./navbar";

interface LandingLayoutProps {
  children: ReactNode;
}

export function LandingLayout({ children }: LandingLayoutProps) {
  return (
    <div className="min-h-screen bg-canvas">
      <Navbar />
      <main>{children}</main>
    </div>
  );
}
