"use client";

import { useCallback, useEffect, useState } from "react";
import {
  deleteTableauIntegration,
  getTableauIntegration,
  saveTableauIntegration,
  setTableauIntegrationEnabled,
  tableauErrorDetail,
  testTableauIntegration,
  type TableauIntegrationInfo,
} from "~/lib/api";
import { useToast } from "~/components/ui/toast";

/** Org Tableau site state and actions for the integrations page. */
export function useTableauIntegration() {
  const { toast } = useToast();
  const [info, setInfo] = useState<TableauIntegrationInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [siteUrl, setSiteUrl] = useState("");
  const [patName, setPatName] = useState("");
  const [patSecret, setPatSecret] = useState("");
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [toggling, setToggling] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);
  const [confirmDisconnect, setConfirmDisconnect] = useState(false);
  /** The last write's failure, shown inline under the form. */
  const [actionError, setActionError] = useState<string | null>(null);

  /** Adopt a gateway answer and reset the form to what is stored. */
  const adopt = useCallback((next: TableauIntegrationInfo) => {
    setInfo(next);
    setSiteUrl(next.configured ? next.site_url ?? "" : "");
    setPatName(next.configured ? next.pat_name ?? "" : "");
    setPatSecret("");
  }, []);

  const fetchIntegration = useCallback(async () => {
    setLoading(true);
    try {
      adopt(await getTableauIntegration());
      setLoadError(false);
    } catch {
      setInfo(null);
      setLoadError(true);
    } finally {
      setLoading(false);
    }
  }, [adopt]);

  useEffect(() => {
    void fetchIntegration();
  }, [fetchIntegration]);

  const configured = Boolean(info?.configured);
  const canSave =
    Boolean(siteUrl.trim()) &&
    Boolean(patName.trim()) &&
    (configured || Boolean(patSecret.trim())) &&
    !saving;

  async function handleSave() {
    if (!canSave) return;
    setSaving(true);
    setActionError(null);
    try {
      const secret = patSecret.trim();
      const next = await saveTableauIntegration({
        site_url: siteUrl.trim(),
        pat_name: patName.trim(),
        ...(secret ? { pat_secret: secret } : {}),
      });
      adopt(next);
      toast("tableau connected", "success");
    } catch (e) {
      setActionError(tableauErrorDetail(e, "could not save the Tableau site"));
    } finally {
      setSaving(false);
    }
  }

  async function handleTest() {
    setTesting(true);
    setActionError(null);
    try {
      const next = await testTableauIntegration();
      setInfo(next);
      if (next.status === "ok") toast("tableau connection ok", "success");
    } catch (e) {
      setActionError(tableauErrorDetail(e, "could not test the Tableau site"));
    } finally {
      setTesting(false);
    }
  }

  async function handleToggleEnabled(enabled: boolean) {
    setToggling(true);
    setActionError(null);
    try {
      setInfo(await setTableauIntegrationEnabled(enabled));
    } catch (e) {
      setActionError(tableauErrorDetail(e, "could not update the Tableau site"));
    } finally {
      setToggling(false);
    }
  }

  async function handleDisconnect() {
    setDisconnecting(true);
    setActionError(null);
    try {
      await deleteTableauIntegration();
      setConfirmDisconnect(false);
      toast("tableau disconnected", "success");
      await fetchIntegration();
    } catch (e) {
      setConfirmDisconnect(false);
      setActionError(tableauErrorDetail(e, "could not disconnect the Tableau site"));
    } finally {
      setDisconnecting(false);
    }
  }

  return {
    info,
    loading,
    loadError,
    siteUrl,
    setSiteUrl,
    patName,
    setPatName,
    patSecret,
    setPatSecret,
    canSave,
    saving,
    testing,
    toggling,
    disconnecting,
    confirmDisconnect,
    setConfirmDisconnect,
    actionError,
    fetchIntegration,
    handleSave,
    handleTest,
    handleToggleEnabled,
    handleDisconnect,
  };
}

export type TableauIntegrationState = ReturnType<typeof useTableauIntegration>;
