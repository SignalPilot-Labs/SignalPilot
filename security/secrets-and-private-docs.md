# Secrets and Private-Document Audit

Audit date: 2026-07-29

## Secret scan result

The GitHub TruffleHog job passed for revision `52c26a8f`. Manual tracked-file review
also found no committed `.env`, private key, PEM, or credential file. Local ignored
credential files exist in the worktree, as expected for development, and their
contents were not copied into this report.

The result is evidence that the configured scanner found no verified secret in the
audited commit range. It is not proof that every historical secret or unsupported
credential format is absent.

## SP-SEC-022 - Internal and third-party documents are tracked in the repository

**Severity: High confidentiality/release risk**

The repository contains tracked planning, customer, vendor, operational, and legal
documents that appear unsuitable for an unrestricted public source release. They
include internal roadmap/work-log material, customer communications, vendor
integration details, and legal working documents. Some reference credential names,
deployment locations, or operational processes but did not contain a verified live
secret in this audit.

The prior audit rated the documents themselves as critical security vulnerabilities.
That overstates the demonstrated technical impact. The correct response depends on
repository visibility, contractual restrictions, and whether the remote branch was
accessible outside the intended team.

**Remediation:**

1. Assign an owner from engineering, legal, and operations to classify every tracked
   non-source document.
2. Remove restricted material from the repository and its reachable Git history.
3. Move required internal material to an access-controlled document system and keep
   only non-sensitive public documentation in source control.
4. Rotate credentials only where review finds an actual value, an exposed reusable
   link, or credible evidence that a referenced credential was disclosed.
5. Add path-based CI policy for high-risk document directories and secret scanning
   on pull requests plus protected-branch history.

## Local-secret handling observations

- The onboarding instructions correctly direct developers to source `GIT_TOKEN`
  from `.env` rather than commit it.
- Default local credentials and encryption material are documented and embedded in
  compose for development. Deployment code must reject those development values in
  shared and cloud environments.
- Security reports should not reproduce credential values, private document
  excerpts, or customer-identifying content. This revision of the report intentionally
  records categories and remediation without duplicating sensitive text.
