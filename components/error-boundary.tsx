"use client";

import React from "react";
import { AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";

interface ErrorBoundaryProps {
  children: React.ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error?: Error;
}

export class ErrorBoundary extends React.Component<
  ErrorBoundaryProps,
  ErrorBoundaryState
> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error("Error caught by boundary:", error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex flex-col items-center justify-center min-h-screen bg-canvas p-4">
          <div className="max-w-md w-full bg-surface-1 border border-hairline rounded-xl p-8 text-center">
            <div className="mb-4 inline-flex rounded-full bg-surface-2 p-4">
              <AlertTriangle className="w-8 h-8 text-gradient-orange" />
            </div>
            <h2 className="text-display-md text-ink mb-2">Something went wrong</h2>
            <p className="text-body text-ink-muted mb-6">
              {this.state.error?.message || "An unexpected error occurred"}
            </p>
            <Button
              onClick={() => this.setState({ hasError: false })}
              className="bg-primary text-on-primary rounded-pill"
            >
              Try again
            </Button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
