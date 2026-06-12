import React, { type JSX } from "react";
import { z } from "zod";
import type { IPlugin, IPluginProps } from "../types";

type FileUploadType = "button" | "area";

/**
 * Arguments for a file upload area/button
 *
 * @param filetypes - file types to accept (same as HTML input's accept attr)
 * @param multiple - whether to allow the user to upload multiple files
 * @param label - a label for the file upload area
 * @param max_size - the maximum size of the file to upload (in bytes)
 */
interface Data {
  filetypes: string[];
  multiple: boolean;
  kind: FileUploadType;
  label: string | null;
  max_size: number;
}

type T = [string, string][];

const LazyFileUpload = React.lazy(
  () => import("./file/file-upload-component"),
);

export class FileUploadPlugin implements IPlugin<T, Data> {
  tagName = "sp-file";

  validator = z.object({
    filetypes: z.array(z.string()),
    multiple: z.boolean(),
    kind: z.enum(["button", "area"]),
    label: z.string().nullable(),
    max_size: z.number(),
  });

  render(props: IPluginProps<T, Data>): JSX.Element {
    return (
      <LazyFileUpload
        label={props.data.label}
        filetypes={props.data.filetypes}
        multiple={props.data.multiple}
        kind={props.data.kind}
        value={props.value}
        setValue={props.setValue}
        max_size={props.data.max_size}
      />
    );
  }
}
