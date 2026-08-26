import React from "react";
import { z } from "zod";
import { createPlugin } from "../core/builder";
import { rpc } from "../core/rpc";

/**
 * File object.
 *
 * @param id - File id
 * @param path - File path
 * @param name - File name
 * @param is_directory - Whether file is a directory or not
 */
interface FileInfo {
  id: string;
  path: string;
  name: string;
  is_directory: boolean;
}

// oxlint-disable-next-line typescript/consistent-type-definitions
type PluginFunctions = {
  list_directory: (req: { path: string }) => Promise<{
    files: FileInfo[];
    total_count: number;
    is_truncated: boolean;
  }>;
};

type S = FileInfo[];

const LazyFileBrowser = React.lazy(
  () => import("./file/file-browser-component"),
);

export const FileBrowserPlugin = createPlugin<S>("sp-file-browser")
  .withData(
    z.object({
      initialPath: z.string(),
      filetypes: z.array(z.string()),
      selectionMode: z.string(),
      multiple: z.boolean(),
      label: z.string().nullable(),
      restrictNavigation: z.boolean(),
    }),
  )
  .withFunctions<PluginFunctions>({
    list_directory: rpc
      .input(
        z.object({
          path: z.string(),
        }),
      )
      .output(
        z.object({
          files: z.array(
            z.object({
              id: z.string(),
              path: z.string(),
              name: z.string(),
              is_directory: z.boolean(),
            }),
          ),
          total_count: z.number(),
          is_truncated: z.boolean(),
        }),
      ),
  })
  .renderer((props) => (
    <LazyFileBrowser
      {...props.data}
      {...props.functions}
      host={props.host}
      value={props.value}
      setValue={props.setValue}
    />
  ));
