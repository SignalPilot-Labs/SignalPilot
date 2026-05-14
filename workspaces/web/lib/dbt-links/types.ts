export const LINK_KINDS = ["native_upload", "github", "dbt_cloud"] as const;
export type LinkKind = (typeof LINK_KINDS)[number];

/**
 * DbtLinkV1 — schemaVersion 1, single shape for all LinkKinds.
 *
 * NOTE (R18): R18 will add kind-specific fields (OAuth tokens, repo URL,
 * tarball path, etc.) under a discriminated union and bump to schemaVersion 2
 * with an explicit forward migration. Do not add kind-specific fields here.
 */
export interface DbtLinkV1 {
  schemaVersion: 1;
  /** UUID v4 */
  id: string;
  /** 1..120 characters */
  name: string;
  kind: LinkKind;
  /** ISO 8601 UTC */
  createdAt: string;
  /**
   * On-disk path of the extracted dbt project, relative to localDbtLinksDir.
   * The loader does not validate that the path exists — that is R18+'s write
   * contract to honor.
   */
  relativePath: string;
}
