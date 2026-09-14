"use client";

import { useCallback, useEffect, useState } from "react";
import { getOrgSecrets, updateOrgSecrets, type OrgSecretsResponse } from "~/lib/api";
import { useToast } from "~/components/ui/toast";

/** Org-level Anthropic key state and actions for the integrations page. */
export function useOrgSecrets() {
  const { toast } = useToast();
  const [orgSecrets, setOrgSecrets] = useState<OrgSecretsResponse | null>(null);
  const [orgSecretsLoading, setOrgSecretsLoading] = useState(true);
  const [orgSecretsLoadError, setOrgSecretsLoadError] = useState(false);
  const [orgSecretsReadOnly, setOrgSecretsReadOnly] = useState(false);
  const [anthropicKey, setAnthropicKey] = useState("");
  const [savingAnthropicKey, setSavingAnthropicKey] = useState(false);
  const [confirmRemoveAnthropicKey, setConfirmRemoveAnthropicKey] = useState(false);

  const fetchOrgSecrets = useCallback(async () => {
    setOrgSecretsLoading(true);
    try {
      const secrets = await getOrgSecrets();
      setOrgSecrets(secrets);
      setOrgSecretsLoadError(false);
    } catch {
      setOrgSecrets(null);
      setOrgSecretsLoadError(true);
    } finally {
      setOrgSecretsLoading(false);
    }
  }, []);

  useEffect(() => { fetchOrgSecrets(); }, [fetchOrgSecrets]);

  async function handleSaveAnthropicKey() {
    const key = anthropicKey.trim();
    if (!key || savingAnthropicKey) return;
    setSavingAnthropicKey(true);
    try {
      const updated = await updateOrgSecrets({ anthropic_api_key: key });
      setOrgSecrets(updated);
      setAnthropicKey("");
      setOrgSecretsReadOnly(false);
      setOrgSecretsLoadError(false);
      toast(orgSecrets?.has_key ? "anthropic key rotated" : "anthropic key saved", "success");
    } catch (e) {
      if (String(e).includes("403:")) {
        setOrgSecretsReadOnly(true);
        toast("you do not have permission to update org secrets", "error");
      } else {
        toast(`failed to save key: ${e}`, "error");
      }
    } finally {
      setSavingAnthropicKey(false);
    }
  }

  async function handleRemoveAnthropicKey() {
    setSavingAnthropicKey(true);
    try {
      const updated = await updateOrgSecrets({ anthropic_api_key: null });
      setOrgSecrets(updated);
      setConfirmRemoveAnthropicKey(false);
      setOrgSecretsReadOnly(false);
      toast("anthropic key removed", "success");
    } catch (e) {
      if (String(e).includes("403:")) {
        setOrgSecretsReadOnly(true);
        toast("you do not have permission to update org secrets", "error");
      } else {
        toast(`failed to remove key: ${e}`, "error");
      }
    } finally {
      setSavingAnthropicKey(false);
    }
  }

  return {
    orgSecrets,
    orgSecretsLoading,
    orgSecretsLoadError,
    orgSecretsReadOnly,
    anthropicKey,
    setAnthropicKey,
    savingAnthropicKey,
    confirmRemoveAnthropicKey,
    setConfirmRemoveAnthropicKey,
    fetchOrgSecrets,
    handleSaveAnthropicKey,
    handleRemoveAnthropicKey,
  };
}

export type OrgSecretsState = ReturnType<typeof useOrgSecrets>;
