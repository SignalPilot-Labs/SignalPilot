import { useAtom, useAtomValue, useSetAtom } from "jotai";
import useEvent from "react-use-event-hook";
import { useImperativeModal } from "@/components/modal/ImperativeModal";
import { Paths } from "@/utils/paths";
import { updateQueryParams } from "@/utils/urls";
import { getAppConfig } from "../config/config";
import { KnownQueryParams } from "../constants";
import { connectionAtom } from "../network/connection";
import { useRequestClient } from "../network/requests";
import { WebSocketState } from "../websocket/types";
import { filenameAtom } from "./file-state";
import { setDocumentTitle } from "../dom/document-title";

export function useFilename() {
  return useAtomValue(filenameAtom);
}

export function useUpdateFilename() {
  const [connection] = useAtom(connectionAtom);
  const setFilename = useSetAtom(filenameAtom);
  const { openAlert } = useImperativeModal();
  const { sendRename } = useRequestClient();

  const handleFilenameChange = useEvent(async (name: string) => {
    const appConfig = getAppConfig();

    // Sessionless (no kernel): naming a notebook is a pure client/store
    // concern — set the filename locally; the follow-up save writes the
    // file through the gateway store. No sandbox involved.
    if (connection.state !== WebSocketState.OPEN) {
      const { canSaveViaGateway } = await import("./gateway-save");
      if (!(await canSaveViaGateway())) {
        openAlert("Failed to save notebook: not connected to a kernel.");
        return null;
      }
      updateQueryParams((params) => {
        params.set(KnownQueryParams.filePath, name);
      });
      setFilename(name);
      setDocumentTitle(
        appConfig.app_title || Paths.basename(name) || "Untitled Notebook",
      );
      return name;
    }

    updateQueryParams((params) => {
      if (name === null) {
        params.delete(KnownQueryParams.filePath);
      } else {
        params.set(KnownQueryParams.filePath, name);
      }
    });

    return sendRename({ filename: name })
      .then(() => {
        setFilename(name);
        setDocumentTitle(
          appConfig.app_title || Paths.basename(name) || "Untitled Notebook",
        );
        return name;
      })
      .catch((error) => {
        openAlert(error.message);
        return null;
      });
  });

  return handleFilenameChange;
}
