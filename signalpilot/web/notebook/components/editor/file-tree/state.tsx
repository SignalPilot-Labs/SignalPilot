import { atom } from "jotai";
import { atomWithStorage } from "jotai/utils";
import { dbtProjectDirAtom } from "@/components/editor/dbt/use-dbt";
import { apiCall, apiCallMultipart } from "@/core/network/api-call";
import type {
  FileCopyRequest,
  FileCopyResponse,
  FileCreateInput,
  FileCreateResponse,
  FileDeleteRequest,
  FileDeleteResponse,
  FileListRequest,
  FileListResponse,
  FileMoveRequest,
  FileMoveResponse,
} from "@/core/network/types";
import { jotaiJsonStorage } from "@/utils/storage/jotai";
import { RequestingTree } from "./requesting-tree";

function createFileOrFolder(
  request: FileCreateInput,
): Promise<FileCreateResponse> {
  const formData = new FormData();
  formData.append("path", request.path);
  formData.append("type", request.type);
  formData.append("name", request.name);
  if (request.file) {
    formData.append("file", request.file, request.name);
  }
  return apiCallMultipart<FileCreateResponse>("/files/create", formData);
}

// State lives outside of the component
// to preserve the state when the component is unmounted
export const treeAtom = atom<RequestingTree>((get) => {
  const dbtProjectDir = get(dbtProjectDirAtom);
  return new RequestingTree(
    {
      listFiles: (req: FileListRequest) =>
        apiCall<FileListResponse>("/files/list_files", req),
      createFileOrFolder,
      deleteFileOrFolder: (req: FileDeleteRequest) =>
        apiCall<FileDeleteResponse>("/files/delete", req),
      copyFileOrFolder: (req: FileCopyRequest) =>
        apiCall<FileCopyResponse>("/files/copy", req),
      renameFileOrFolder: (req: FileMoveRequest) =>
        apiCall<FileMoveResponse>("/files/move", req),
    },
    dbtProjectDir || undefined,
  );
});

export const openStateAtom = atomWithStorage<Record<string, boolean>>(
  "sp:file-tree-open-state",
  {},
  jotaiJsonStorage,
  { getOnInit: true },
);
