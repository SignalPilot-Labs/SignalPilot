import React, { type JSX, lazy } from "react";
import { z } from "zod";
import type {
  IStatelessPlugin,
  IStatelessPluginProps,
} from "../stateless-plugin";

interface Data {
  /**
   * The title of the progress bar.
   */
  title?: string;
  /**
   * The subtitle of the progress bar.
   */
  subtitle?: string;
  /**
   * The progress of the progress bar.
   * Number from 0 to 100, or `true` to indicate indeterminate progress if the count is unknown.
   */
  progress: number | boolean;
  /**
   * The total value of the progress bar.
   */
  total?: number;
  /**
   * The estimated time remaining in seconds.
   */
  eta?: number;
  /**
   * The rate of progress in items per second.
   */
  rate?: number;
}

const LazyProgress = lazy(() => import("./progress-component"));

export class ProgressPlugin implements IStatelessPlugin<Data> {
  tagName = "sp-progress";

  validator = z.object({
    title: z.string().optional(),
    subtitle: z.string().optional(),
    progress: z.union([z.number(), z.boolean()]),
    total: z.number().optional(),
    eta: z.number().optional(),
    rate: z.number().optional(),
  });

  render(props: IStatelessPluginProps<Data>): JSX.Element {
    return <LazyProgress {...props.data} />;
  }
}
