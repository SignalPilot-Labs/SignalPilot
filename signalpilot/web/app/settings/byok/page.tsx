"use client";

import { useEffect, useState, useCallback } from "react";
import {
  Shield,
  Plus,
  Trash2,
  Loader2,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  RefreshCw,
  Key,
} from "lucide-react";
import { PageHeader, TerminalBar } from "@/components/ui/page-header";
import { SectionHeader } from "@/components/ui/section-header";
import { StatusDot } from "@/components/ui/data-viz";
import { useToast } from "@/components/ui/toast";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import {
  listBYOKKeys,
  createBYOKKey,
  deleteBYOKKey,
  validateBYOKKey,
  getBYOKStatus,
  migrateToBYOK,
  revertToManaged,
} from "@/lib/api";
import type { BYOKKey, BYOKStatus } from "@/lib/api";

const IS_CLOUD_MODE = process.env.NEXT_PUBLIC_DEPLOYMENT_MODE === "cloud";

export default function BYOKPage() {
  const { toast } = useToast();
  const [keys, setKeys] = useState<BYOKKey[]>([]);
  const [status, setStatus] = useState<BYOKStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Create form
  const [showCreate, setShowCreate] = useState(false);
  const [createAlias, setCreateAlias] = useState("");
  const [createProvider, setCreateProvider] = useState("local");
  const [creating, setCreating] = useState(false);
  // Provider-specific config
  const [awsKmsArn, setAwsKmsArn] = useState("");
  const [awsRegion, setAwsRegion] = useState("us-east-1");
  const [awsAccessKeyId, setAwsAccessKeyId] = useState("");
  const [awsSecretKey, setAwsSecretKey] = useState("");
  const [gcpKeyResource, setGcpKeyResource] = useState("");
  const [gcpServiceAccountJson, setGcpServiceAccountJson] = useState("");
  const [azureVaultUrl, setAzureVaultUrl] = useState("");
  const [azureKeyName, setAzureKeyName] = useState("");
  const [azureTenantId, setAzureTenantId] = useState("");
  const [azureClientId, setAzureClientId] = useState("");
  const [azureClientSecret, setAzureClientSecret] = useState("");

  // Actions
  const [validating, setValidating] = useState<string | null>(null);
  const [validationResults, setValidationResults] = useState<Record<string, { valid: boolean; error?: string }>>({});
  const [migrating, setMigrating] = useState(false);
  const [reverting, setReverting] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [forceDelete, setForceDelete] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [keyList, byokStatus] = await Promise.all([
        listBYOKKeys().catch(() => []),
        getBYOKStatus().catch(() => null),
      ]);
      setKeys(keyList);
      setStatus(byokStatus);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load encryption config");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  function buildProviderConfig(): Record<string, unknown> | undefined {
    switch (createProvider) {
      case "aws_kms":
        if (!awsKmsArn.trim()) return undefined;
        return {
          kms_key_arn: awsKmsArn.trim(),
          region: awsRegion.trim() || "us-east-1",
          aws_access_key_id: awsAccessKeyId.trim() || undefined,
          aws_secret_access_key: awsSecretKey.trim() || undefined,
        };
      case "gcp_kms":
        if (!gcpKeyResource.trim()) return undefined;
        return {
          key_resource_name: gcpKeyResource.trim(),
          service_account_json: gcpServiceAccountJson.trim() || undefined,
        };
      case "azure_kv":
        if (!azureVaultUrl.trim() || !azureKeyName.trim()) return undefined;
        return {
          vault_url: azureVaultUrl.trim(),
          key_name: azureKeyName.trim(),
          tenant_id: azureTenantId.trim() || undefined,
          client_id: azureClientId.trim() || undefined,
          client_secret: azureClientSecret.trim() || undefined,
        };
      default:
        return undefined;
    }
  }

  async function handleCreate() {
    if (!createAlias.trim()) return;
    if (createProvider === "aws_kms" && !awsKmsArn.trim()) {
      toast("KMS Key ARN is required for AWS KMS", "error"); return;
    }
    if (createProvider === "gcp_kms" && !gcpKeyResource.trim()) {
      toast("Key resource name is required for GCP Cloud KMS", "error"); return;
    }
    if (createProvider === "azure_kv" && (!azureVaultUrl.trim() || !azureKeyName.trim())) {
      toast("Vault URL and key name are required for Azure Key Vault", "error"); return;
    }
    setCreating(true);
    try {
      await createBYOKKey({
        key_alias: createAlias.trim(),
        provider_type: createProvider,
        provider_config: buildProviderConfig(),
      });
      toast("encryption key registered", "success");
      setShowCreate(false);
      setCreateAlias("");
      setAwsKmsArn(""); setAwsAccessKeyId(""); setAwsSecretKey(""); setGcpKeyResource(""); setGcpServiceAccountJson(""); setAzureVaultUrl(""); setAzureKeyName(""); setAzureTenantId(""); setAzureClientId(""); setAzureClientSecret("");
      refresh();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Failed to create key", "error");
    } finally {
      setCreating(false);
    }
  }

  async function handleValidate(keyId: string) {
    setValidating(keyId);
    try {
      const result = await validateBYOKKey(keyId);
      setValidationResults((prev) => ({ ...prev, [keyId]: result }));
      toast(result.valid ? "Key validated successfully" : `Validation failed: ${result.error}`, result.valid ? "success" : "error");
    } catch (e) {
      toast("Validation request failed", "error");
    } finally {
      setValidating(null);
    }
  }

  async function handleDelete() {
    if (!deleteTarget) return;
    try {
      await deleteBYOKKey(deleteTarget);
      // Optimistic UI: remove from list immediately
      setKeys((prev) => prev.filter((k) => k.id !== deleteTarget));
      toast("Key deleted", "success");
      setDeleteTarget(null);
      setForceDelete(false);
      refresh();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      if (msg.includes("409") || msg.includes("in use")) {
        // Key is in use — escalate to force-delete confirmation
        setForceDelete(true);
      } else {
        toast(msg, "error");
      }
    }
  }

  async function handleForceDelete() {
    if (!deleteTarget) return;
    try {
      await deleteBYOKKey(deleteTarget, true);
      // Optimistic UI: remove from list immediately
      setKeys((prev) => prev.filter((k) => k.id !== deleteTarget));
      toast("Key revoked — credentials reverted to managed encryption", "success");
      setDeleteTarget(null);
      setForceDelete(false);
      refresh();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Force delete failed", "error");
    }
  }

  async function handleMigrate(keyId: string) {
    setMigrating(true);
    try {
      const result = await migrateToBYOK(keyId);
      toast(`Migrated ${result.migrated} credential(s) to bring-your-own-key${result.failed ? `, ${result.failed} failed` : ""}`, result.failed ? "error" : "success");
      refresh();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Migration failed", "error");
    } finally {
      setMigrating(false);
    }
  }

  async function handleRevert() {
    setReverting(true);
    try {
      const result = await revertToManaged();
      toast(`Reverted ${result.migrated} credential(s) to managed encryption${result.failed ? `, ${result.failed} failed` : ""}`, result.failed ? "error" : "success");
      refresh();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Revert failed", "error");
    } finally {
      setReverting(false);
    }
  }

  const activeKeys = keys.filter((k) => k.status === "active");
  const hasKeys = activeKeys.length > 0;

  return (
    <div className="p-8 max-w-3xl animate-fade-in">
      <PageHeader
        title="security"
        subtitle="bring-your-own-key"
        description="encrypt database credentials with your own keys — you control the master key, SignalPilot never sees it"
      />

      <TerminalBar path="settings/security --config">
        <div className="flex items-center gap-6 text-xs">
          {status && (
            <>
              <span className="text-[var(--color-text-dim)]">
                encryption: <code className={status.status === "complete" ? "text-emerald-400" : status.status === "partial" ? "text-amber-400" : "text-[var(--color-text-muted)]"}>{status.status}</code>
              </span>
              <span className="text-[var(--color-text-dim)]">
                bring-your-own-key: <code>{status.byok}</code> / managed: <code>{status.managed}</code>
              </span>
            </>
          )}
        </div>
      </TerminalBar>

      {loading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="w-5 h-5 animate-spin text-[var(--color-text-dim)]" />
        </div>
      ) : error ? (
        <div className="border border-red-500/30 bg-red-500/5 p-4 text-[12px] text-red-400 tracking-wider">
          {error}
        </div>
      ) : (
        <>
          {/* Keys Section */}
          <section className="mb-8">
            <SectionHeader icon={Key} title="encryption keys" />
            <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] overflow-hidden">
              <div className="p-6">
                {keys.length === 0 && !showCreate ? (
                  <div className="text-center py-8">
                    <Shield className="w-8 h-8 text-[var(--color-text-dim)] mx-auto mb-3" strokeWidth={1} />
                    <p className="text-[12px] text-[var(--color-text-muted)] tracking-wider mb-1">no encryption keys configured</p>
                    <p className="text-[11px] text-[var(--color-text-dim)] tracking-wider mb-4">
                      credentials are encrypted with SignalPilot&apos;s managed key
                    </p>
                    <button
                      onClick={() => setShowCreate(true)}
                      className="inline-flex items-center gap-2 px-4 py-2 text-xs tracking-wider uppercase border border-[var(--color-border)] text-[var(--color-text-dim)] hover:text-[var(--color-text)] hover:border-[var(--color-text)] transition-all"
                    >
                      <Plus className="w-3.5 h-3.5" /> register a key
                    </button>
                  </div>
                ) : (
                  <div className="space-y-3">
                    {keys.map((key) => {
                      const vr = validationResults[key.id];
                      return (
                        <div key={key.id} className={`flex items-center justify-between p-3 border ${key.status === "active" ? "border-[var(--color-border)]" : "border-red-500/20 bg-red-500/5"}`}>
                          <div className="flex items-center gap-3">
                            <StatusDot status={key.status === "active" ? "healthy" : "error"} size={4} />
                            <div>
                              <div className="flex items-center gap-2">
                                <code className="text-[13px] text-[var(--color-text)] tracking-wider">{key.key_alias}</code>
                                <span className="text-[10px] px-1.5 py-0.5 border border-[var(--color-border)] text-[var(--color-text-dim)] tracking-wider uppercase">{key.provider_type}</span>
                                <span className={`text-[10px] px-1.5 py-0.5 border tracking-wider uppercase ${key.status === "active" ? "border-emerald-500/30 text-emerald-400" : "border-red-500/30 text-red-400"}`}>{key.status}</span>
                              </div>
                              <p className="text-[10px] text-[var(--color-text-dim)] tracking-wider mt-0.5">
                                created {new Date(key.created_at * 1000).toLocaleDateString()}
                                {key.revoked_at && ` — revoked ${new Date(key.revoked_at * 1000).toLocaleDateString()}`}
                              </p>
                            </div>
                          </div>
                          <div className="flex items-center gap-2">
                            {vr && (
                              <span className={`text-[10px] tracking-wider ${vr.valid ? "text-emerald-400" : "text-red-400"}`}>
                                {vr.valid ? "valid" : "invalid"}
                              </span>
                            )}
                            <button
                              onClick={() => handleValidate(key.id)}
                              disabled={validating === key.id}
                              className="p-1.5 text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors"
                              title="Validate key"
                            >
                              {validating === key.id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <CheckCircle2 className="w-3.5 h-3.5" strokeWidth={1.5} />}
                            </button>
                            {key.status === "active" && !migrating && (
                              <button
                                onClick={() => handleMigrate(key.id)}
                                className="px-2 py-1 text-[10px] tracking-wider uppercase border border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/10 transition-all"
                              >
                                migrate
                              </button>
                            )}
                            <button
                              onClick={() => setDeleteTarget(key.id)}
                              className="p-1.5 text-[var(--color-text-dim)] hover:text-red-400 transition-colors"
                              title="Delete key"
                            >
                              <Trash2 className="w-3.5 h-3.5" strokeWidth={1.5} />
                            </button>
                          </div>
                        </div>
                      );
                    })}

                    {!showCreate && (
                      <button
                        onClick={() => setShowCreate(true)}
                        className="flex items-center gap-2 px-3 py-2 text-[11px] tracking-wider text-[var(--color-text-dim)] hover:text-[var(--color-text)] border border-dashed border-[var(--color-border)] hover:border-[var(--color-text)] transition-all w-full justify-center"
                      >
                        <Plus className="w-3 h-3" /> add key
                      </button>
                    )}
                  </div>
                )}

                {/* Create form */}
                {showCreate && (
                  <div className="mt-4 p-4 border border-[var(--color-border)] bg-[var(--color-bg)]/50">
                    <p className="text-[12px] text-[var(--color-text-muted)] tracking-wider mb-3">register encryption key</p>
                    <div className="grid grid-cols-2 gap-3 mb-3">
                      <div>
                        <label className="block text-[11px] text-[var(--color-text-dim)] mb-1 tracking-wider">key alias</label>
                        <input
                          value={createAlias}
                          onChange={(e) => setCreateAlias(e.target.value)}
                          placeholder="my-encryption-key"
                          className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)] tracking-wide"
                        />
                      </div>
                      <div>
                        <label className="block text-[11px] text-[var(--color-text-dim)] mb-1 tracking-wider">provider</label>
                        <select
                          value={createProvider}
                          onChange={(e) => setCreateProvider(e.target.value)}
                          className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)] tracking-wide"
                        >
                          {!IS_CLOUD_MODE && <option value="local">local (auto-generated)</option>}
                          <option value="aws_kms">AWS KMS</option>
                          <option value="gcp_kms">GCP Cloud KMS</option>
                          <option value="azure_kv">Azure Key Vault</option>
                        </select>
                      </div>
                    </div>

                    {/* Provider-specific config fields */}
                    {createProvider === "local" && (
                      <div className="mb-3 px-3 py-2 border border-[var(--color-border)] border-dashed text-[11px] text-[var(--color-text-dim)] tracking-wider">
                        key material is auto-generated and stored in memory. suitable for development and testing only.
                      </div>
                    )}

                    {createProvider === "aws_kms" && (
                      <div className="mb-3 space-y-3">
                        <div>
                          <label className="block text-[11px] text-[var(--color-text-dim)] mb-1 tracking-wider">KMS key ARN *</label>
                          <input
                            value={awsKmsArn}
                            onChange={(e) => setAwsKmsArn(e.target.value)}
                            placeholder="arn:aws:kms:us-east-1:123456789:key/abcd-1234-..."
                            className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)] tracking-wide font-mono"
                          />
                        </div>
                        <div className="grid grid-cols-3 gap-3">
                          <div>
                            <label className="block text-[11px] text-[var(--color-text-dim)] mb-1 tracking-wider">region</label>
                            <input
                              value={awsRegion}
                              onChange={(e) => setAwsRegion(e.target.value)}
                              placeholder="us-east-1"
                              className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)] tracking-wide"
                            />
                          </div>
                          <div>
                            <label className="block text-[11px] text-[var(--color-text-dim)] mb-1 tracking-wider">access key ID *</label>
                            <input
                              value={awsAccessKeyId}
                              onChange={(e) => setAwsAccessKeyId(e.target.value)}
                              placeholder="AKIA..."
                              className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)] tracking-wide font-mono"
                            />
                          </div>
                          <div>
                            <label className="block text-[11px] text-[var(--color-text-dim)] mb-1 tracking-wider">secret access key *</label>
                            <input
                              type="password"
                              value={awsSecretKey}
                              onChange={(e) => setAwsSecretKey(e.target.value)}
                              placeholder="wJalrXUtnFEMI..."
                              className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)] tracking-wide font-mono"
                            />
                          </div>
                        </div>
                        <div className="px-3 py-2 border border-[var(--color-border)] border-dashed text-[10px] text-[var(--color-text-dim)] tracking-wider">
                          the IAM user needs <code className="text-[var(--color-text-muted)]">kms:Encrypt</code>, <code className="text-[var(--color-text-muted)]">kms:Decrypt</code>, <code className="text-[var(--color-text-muted)]">kms:GenerateDataKey</code> permissions on the key. credentials are stored encrypted and never leave SignalPilot.
                        </div>
                      </div>
                    )}

                    {createProvider === "gcp_kms" && (
                      <div className="mb-3 space-y-3">
                        <div>
                          <label className="block text-[11px] text-[var(--color-text-dim)] mb-1 tracking-wider">key resource name *</label>
                          <input
                            value={gcpKeyResource}
                            onChange={(e) => setGcpKeyResource(e.target.value)}
                            placeholder="projects/my-project/locations/global/keyRings/my-ring/cryptoKeys/my-key"
                            className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)] tracking-wide font-mono"
                          />
                        </div>
                        <div>
                          <label className="block text-[11px] text-[var(--color-text-dim)] mb-1 tracking-wider">service account JSON key *</label>
                          <textarea
                            value={gcpServiceAccountJson}
                            onChange={(e) => setGcpServiceAccountJson(e.target.value)}
                            placeholder='{"type": "service_account", "project_id": "...", ...}'
                            rows={4}
                            className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)] tracking-wide font-mono resize-y"
                          />
                          <p className="text-[10px] text-[var(--color-text-dim)] mt-1 tracking-wider opacity-60">
                            paste the full JSON contents of your service account key file. the service account needs the <code className="text-[var(--color-text-muted)]">Cloud KMS CryptoKey Encrypter/Decrypter</code> role.
                          </p>
                        </div>
                      </div>
                    )}

                    {createProvider === "azure_kv" && (
                      <div className="mb-3 space-y-3">
                        <div className="grid grid-cols-2 gap-3">
                          <div>
                            <label className="block text-[11px] text-[var(--color-text-dim)] mb-1 tracking-wider">vault URL *</label>
                            <input
                              value={azureVaultUrl}
                              onChange={(e) => setAzureVaultUrl(e.target.value)}
                              placeholder="https://my-vault.vault.azure.net"
                              className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)] tracking-wide font-mono"
                            />
                          </div>
                          <div>
                            <label className="block text-[11px] text-[var(--color-text-dim)] mb-1 tracking-wider">key name *</label>
                            <input
                              value={azureKeyName}
                              onChange={(e) => setAzureKeyName(e.target.value)}
                              placeholder="my-encryption-key"
                              className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)] tracking-wide"
                            />
                          </div>
                        </div>
                        <div className="grid grid-cols-3 gap-3">
                          <div>
                            <label className="block text-[11px] text-[var(--color-text-dim)] mb-1 tracking-wider">tenant ID *</label>
                            <input
                              value={azureTenantId}
                              onChange={(e) => setAzureTenantId(e.target.value)}
                              placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
                              className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)] tracking-wide font-mono"
                            />
                          </div>
                          <div>
                            <label className="block text-[11px] text-[var(--color-text-dim)] mb-1 tracking-wider">client ID *</label>
                            <input
                              value={azureClientId}
                              onChange={(e) => setAzureClientId(e.target.value)}
                              placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
                              className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)] tracking-wide font-mono"
                            />
                          </div>
                          <div>
                            <label className="block text-[11px] text-[var(--color-text-dim)] mb-1 tracking-wider">client secret *</label>
                            <input
                              type="password"
                              value={azureClientSecret}
                              onChange={(e) => setAzureClientSecret(e.target.value)}
                              placeholder="..."
                              className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)] tracking-wide font-mono"
                            />
                          </div>
                        </div>
                        <div className="px-3 py-2 border border-[var(--color-border)] border-dashed text-[10px] text-[var(--color-text-dim)] tracking-wider">
                          the service principal needs the <code className="text-[var(--color-text-muted)]">Key Vault Crypto User</code> role on the key vault. assign via Azure Portal &rarr; Key Vault &rarr; Access control (IAM). credentials are stored encrypted and never leave SignalPilot.
                        </div>
                      </div>
                    )}
                    <div className="flex items-center gap-2">
                      <button
                        onClick={handleCreate}
                        disabled={creating || !createAlias.trim()}
                        className="flex items-center gap-2 px-4 py-2 bg-[var(--color-text)] text-[var(--color-bg)] text-xs font-medium tracking-wider uppercase hover:opacity-90 disabled:opacity-30 transition-all"
                      >
                        {creating && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                        register key
                      </button>
                      <button
                        onClick={() => { setShowCreate(false); setCreateAlias(""); }}
                        className="px-4 py-2 text-xs text-[var(--color-text-dim)] hover:text-[var(--color-text)] tracking-wider transition-colors"
                      >
                        cancel
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </section>

          {/* Migration Status Section */}
          {status && (
            <section className="mb-8">
              <SectionHeader icon={RefreshCw} title="migration status" />
              <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] overflow-hidden">
                <div className="p-6">
                  <div className="grid grid-cols-3 gap-4 mb-4">
                    <div className="p-3 border border-[var(--color-border)]">
                      <p className="text-[10px] text-[var(--color-text-dim)] tracking-wider uppercase mb-1">total credentials</p>
                      <p className="text-[20px] text-[var(--color-text)] tabular-nums">{status.total}</p>
                    </div>
                    <div className="p-3 border border-emerald-500/20">
                      <p className="text-[10px] text-emerald-400 tracking-wider uppercase mb-1">your key</p>
                      <p className="text-[20px] text-emerald-400 tabular-nums">{status.byok}</p>
                    </div>
                    <div className="p-3 border border-[var(--color-border)]">
                      <p className="text-[10px] text-[var(--color-text-dim)] tracking-wider uppercase mb-1">managed</p>
                      <p className="text-[20px] text-[var(--color-text-muted)] tabular-nums">{status.managed}</p>
                    </div>
                  </div>

                  {status.byok > 0 && (
                    <div className="flex items-start gap-2 p-3 border border-amber-500/20 bg-amber-500/5 mb-4">
                      <AlertTriangle className="w-3.5 h-3.5 text-amber-400 flex-shrink-0 mt-0.5" strokeWidth={1.5} />
                      <div>
                        <p className="text-[11px] text-amber-400 tracking-wider">
                          {status.byok} credential(s) encrypted with your key. revoking your key will make these credentials unreadable.
                        </p>
                      </div>
                    </div>
                  )}

                  {status.byok > 0 && (
                    <button
                      onClick={handleRevert}
                      disabled={reverting}
                      className="flex items-center gap-2 px-3 py-2 text-[11px] tracking-wider border border-amber-500/30 text-amber-400 hover:bg-amber-500/10 transition-all"
                    >
                      {reverting ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" strokeWidth={1.5} />}
                      revert all to managed encryption
                    </button>
                  )}
                </div>
              </div>
            </section>
          )}

          {/* How it works */}
          <section className="mb-8">
            <SectionHeader icon={Shield} title="how bring-your-own-key works" />
            <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] overflow-hidden">
              <div className="p-6 space-y-3 text-[11px] text-[var(--color-text-dim)] tracking-wider leading-relaxed">
                <p><span className="text-[var(--color-text-muted)]">1.</span> you register a master key (KEK) — stored in your KMS, never leaves your infrastructure</p>
                <p><span className="text-[var(--color-text-muted)]">2.</span> SignalPilot generates a data encryption key (DEK) per credential, wraps it with your KEK</p>
                <p><span className="text-[var(--color-text-muted)]">3.</span> credentials are encrypted with the DEK — SignalPilot stores only the wrapped DEK + ciphertext</p>
                <p><span className="text-[var(--color-text-muted)]">4.</span> on query, SignalPilot unwraps the DEK via your KMS, decrypts the credential, connects</p>
                <p><span className="text-[var(--color-text-muted)]">5.</span> revoke your key at any time — all bring-your-own-key credentials become immediately unreadable</p>
              </div>
            </div>
          </section>
        </>
      )}

      <ConfirmDialog
        open={deleteTarget !== null && !forceDelete}
        title="delete encryption key"
        message="This will permanently delete this encryption key. If credentials are using it, you'll be asked to confirm revoking access."
        confirmLabel="delete"
        variant="danger"
        onConfirm={handleDelete}
        onCancel={() => { setDeleteTarget(null); setForceDelete(false); }}
      />

      <ConfirmDialog
        open={forceDelete && deleteTarget !== null}
        title="revoke access — are you sure?"
        message="This key is actively encrypting database credentials. Deleting it will permanently destroy access to those credentials. Affected connections will stop working and must be re-created with new credentials. This cannot be undone."
        confirmLabel="revoke and destroy"
        variant="danger"
        onConfirm={handleForceDelete}
        onCancel={() => { setDeleteTarget(null); setForceDelete(false); }}
      />
    </div>
  );
}
