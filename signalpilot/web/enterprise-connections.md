# Enterprise SSO Connections (SAML / OIDC)

SignalPilot uses Clerk's **Enterprise Connections** feature to let enterprise
customers sign in with their own identity provider (IdP). All configuration
happens in the Clerk dashboard — no code changes required on the SignalPilot
side. The same sign-in page at `/sign-in` transparently routes users through
their IdP when their email domain matches a configured connection.

This document is the playbook SignalPilot admins follow when onboarding a
new enterprise customer who requests SSO.

---

## Who should read this

- SignalPilot ops / customer success setting up SSO for a new enterprise tenant.
- Engineers verifying the connection is wired correctly.

## Prerequisites

1. Clerk **Enterprise plan** (or Pro with the SSO add-on). Check the billing
   page before starting.
2. The customer has an admin-level contact at their IdP (Okta, Azure AD,
   Google Workspace, OneLogin, JumpCloud, generic SAML, or a generic OIDC
   provider).
3. The customer has decided which email domain(s) should be tied to the SSO
   connection (e.g. `@acme.com`). Subdomains require separate entries.
4. The customer has a Team (Clerk Organization) already created in the
   SignalPilot app. Enterprise connections are scoped to an organization.

## Step 1 — Create the connection in Clerk

1. Log into the Clerk dashboard for the production instance
   (`endless-fly-19.clerk.accounts.dev` for dev keys; production hostname
   when going live).
2. Navigate to **User & Authentication → Enterprise Connections**.
3. Click **Add connection**.
4. Pick the provider template: **SAML** or **OIDC**. For well-known IdPs,
   choose the template (Okta, Azure AD, Google Workspace) — Clerk pre-fills
   metadata URLs.
5. Name the connection after the customer (e.g. `acme-okta`).
6. Scope: select the customer's **Organization** under "Assign to
   organization" (this is what ties the connection to their Team).
7. Add the customer's email domain(s) under **Domains** (e.g. `acme.com`).
   Clerk will route any sign-in attempt with a matching domain through this
   IdP.

## Step 2 — Exchange metadata with the customer IdP

### SAML

- **From Clerk → give to customer:**
  - ACS (Assertion Consumer Service) URL
  - Entity ID / Audience URI
  - Clerk's SP metadata XML (downloadable from the connection page)
- **From customer IdP → give to Clerk:**
  - IdP SSO URL (Single Sign-On URL)
  - IdP Issuer
  - X.509 signing certificate (PEM)
  - Or a single **IdP metadata URL** Clerk will poll (preferred when the IdP
    supports it — Okta and Azure AD both do).

Attribute mapping (SAML assertion → Clerk user):

| Clerk field      | SAML attribute                                                  |
| ---------------- | --------------------------------------------------------------- |
| `email_address`  | `http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress` or `NameID` |
| `first_name`     | `givenName`                                                     |
| `last_name`      | `surname`                                                       |

### OIDC

- **From Clerk:** callback URL (redirect URI) to register in the IdP.
- **From IdP:** `client_id`, `client_secret`, `issuer` (discovery URL
  preferred so Clerk can auto-fetch `/.well-known/openid-configuration`).

OIDC scopes required: `openid profile email`.

## Step 3 — Enable the connection

1. In the Clerk dashboard, toggle the connection to **Enabled**.
2. Toggle **Auto-provisioning** ON if the customer wants new users to be
   created automatically on first SSO login (recommended).
3. Toggle **Just-in-time organization membership** ON so SSO users are
   added to the scoped Team automatically.

## Step 4 — Verify the flow end-to-end

1. Visit `https://app.signalpilot.ai/sign-in` (or staging URL).
2. Type the customer's email (e.g. `alice@acme.com`) into the email field.
3. Press continue. Clerk recognizes the domain and redirects to the IdP.
4. Log in at the IdP.
5. Confirm redirect back to SignalPilot → user lands inside the customer's
   Team with the correct role.
6. Open Clerk dashboard → Users and confirm the new user has the IdP
   identifier attached.

## Step 5 — Role mapping (optional)

If the customer wants IdP group → SignalPilot role mapping:

1. In the Clerk connection settings, open **Attribute mapping**.
2. Map the IdP group claim (e.g. `groups` for Azure AD) to Clerk's
   `organization_roles`.
3. Define the role mapping (`admin` if group contains `signalpilot-admins`,
   otherwise `member`). Currently SignalPilot only uses `admin` and `member`
   roles — anything else collapses to `member`.

## In-app status view

SignalPilot exposes a read-only enterprise SSO status panel inside
**Settings → Team** (the "enterprise sso" section, between Invitations and
Danger Zone). Team admins can check connection status without opening the
Clerk dashboard for routine inquiries.

### What it shows

- Connection name, protocol (SAML or OIDC), email domains, and active/inactive
  status for every enterprise connection scoped to the current team.
- For SAML connections: an expandable **IdP handoff details** panel with
  one-click copy for the SP-side fields the customer's IdP admin needs:
  - ACS (Assertion Consumer Service) URL
  - SP Entity ID
  - SP Metadata URL
  - IdP Entity ID (as returned by Clerk)
  - IdP SSO URL (as returned by Clerk)
- For OIDC connections: protocol, domains, and status only (the OIDC redirect
  URI hand-off is a one-shot exchange covered in Step 2 above).

### What it does NOT show

- No create, update, or delete controls — all configuration changes must be
  made in the Clerk dashboard per the ops playbook.
- No X.509 signing certificates or other private IdP credential material.
- No OIDC client secrets (the Clerk Backend SDK does not return them on read).

### Route — `GET /api/team/enterprise`

- **Auth model:** requires an active Clerk session (`userId` present) with an
  active organization (`orgId` present) and the caller must hold
  `org:admin` role (`orgRole === "org:admin"`). Non-admins receive `403
  Forbidden`.
- **Defensive filter:** after the Clerk SDK call, the response is additionally
  filtered on `organizationId === orgId` so a misconfigured SDK parameter
  cannot leak another tenant's connections.
- **Response shape:** a whitelisted DTO (`EnterpriseConnectionDTO`) — no SDK
  object is spread into the response. Fields not in the DTO are never returned.

Non-admin team members see a "enterprise sso is managed by your team admins"
stub and no network request is issued.

## Troubleshooting

| Symptom                                             | Likely cause                                                  |
| --------------------------------------------------- | ------------------------------------------------------------- |
| "No enterprise connection found" on sign-in         | Domain not registered on the connection, or connection disabled |
| Redirects to IdP then back to sign-in with an error | ACS URL or Entity ID mismatch                                  |
| Signs in but lands in wrong Team                    | Connection scoped to wrong org; re-scope in dashboard         |
| User's name shows as email                          | Attribute mapping missing `givenName` / `surname`              |
| SCIM provisioning not working                       | SCIM is a separate Clerk feature — outside the scope of SSO    |

## Security notes

- Enterprise connections bypass SignalPilot's password policy — the IdP owns
  the password policy.
- MFA enforcement: if the customer's IdP enforces MFA, we inherit it. If they
  don't and want us to layer Clerk's MFA on top, set **Require MFA** on the
  Organization in the Clerk dashboard.
- Session lifetime: IdP session is independent from Clerk's session. Signing
  out of SignalPilot does not sign the user out of their IdP.
- Always use the **production** Clerk instance for real customers — do not
  use the dev keys (`pk_test_...`).

## Customer-facing onboarding checklist (for comms)

Send the customer this one-pager:

1. Your IT admin will need to create a SAML or OIDC app in your IdP.
2. We will send you two URLs (ACS URL and Entity ID for SAML, or a
   redirect URI for OIDC).
3. You will send us your IdP metadata URL (or signing cert + SSO URL).
4. We'll configure the connection and send you a test link.
5. Have one pilot user log in. Once confirmed, we'll roll out to your full
   team.
6. All users with your email domain will automatically route through SSO
   the next time they sign in.

Estimated total time: 30–60 minutes of elapsed work per customer.
