"use client";

import { Component, type ErrorInfo, type ReactNode } from "react";

import styles from "./dashboard-runtime.module.css";

function fingerprintRenderFailure(error: Error, info: ErrorInfo): string {
  const input = `${error.name}:${info.componentStack ?? "dashboard-chart"}`;
  let hash = 2166136261;
  for (let index = 0; index < input.length; index += 1) {
    hash ^= input.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return `render-${(hash >>> 0).toString(16)}`;
}

export class DashboardRenderBoundary extends Component<
  {
    children: ReactNode;
    resetKey: string;
    onFailure: (fingerprint: string) => void;
  },
  { failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    this.props.onFailure(fingerprintRenderFailure(error, info));
  }

  componentDidUpdate(previous: Readonly<{ resetKey: string }>) {
    if (previous.resetKey !== this.props.resetKey && this.state.failed) {
      this.setState({ failed: false });
    }
  }

  render() {
    if (this.state.failed) {
      return (
        <div className={styles.chartBrokenState} role="status">
          <strong>Unable to display this chart</strong>
          <p>
            The chart could not be rendered. Refresh the dashboard to try again.
          </p>
        </div>
      );
    }
    return this.props.children;
  }
}
