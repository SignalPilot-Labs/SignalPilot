# Clerk Research — SignalPilot Team-First Rework

Captured: 2026-04-23 (round 1). This is the durable artifact future rounds should read
instead of re-researching. If you change any dependency version, update the notes
at the top of the relevant section.

---

## 1. Installed versions (web/package.json)

- `@clerk/nextjs@^7.2.4` — already installed.
- `@clerk/elements` — **NOT yet installed** (add in round 1 as a dependency).
  Install with `npm install @clerk/elements`. Requires Next.js App Router +
  Clerk Core 2 (our version is compatible). Status: beta, stable enough for
  production use; Clerk is signaling "Core 3 hooks" will eventually replace
  it but Elements is still the recommended way to build fully custom flows today.
- TypeScript `tsconfig.json` already uses `moduleResolution: "bundler"` (verify
  when adding). Required by `@clerk/elements`.

## 2. Clerk Elements — overview

Clerk Elements is an **unstyled** headless primitive library exposing the
underlying sign-in / sign-up state machine. You build the UI; Clerk drives
flow state (current step, strategy, field validation, server errors).

### Imports

```ts
import * as Clerk from "@clerk/elements/common";
import * as SignIn from "@clerk/elements/sign-in";
import * as SignUp from "@clerk/elements/sign-up";
```

### Primitive glossary

Common (`Clerk.*`):

- `Clerk.GlobalError` — renders `lastError` from Clerk (server side errors).
- `Clerk.Field name="identifier|password|code|emailAddress|..."` — wraps
  a single form field. Provides context for Label/Input/FieldError.
- `Clerk.Label` — `<label>` with correct `htmlFor` wiring.
- `Clerk.Input type="email|password|text|tel|otp"` — input bound to the flow.
  `type="otp"` renders a 6-box OTP input (accessible, built-in).
- `Clerk.FieldError` — per-field error slot, auto-populated from Clerk.
- `Clerk.Loading` — render prop `{(isLoading) => ...}` for per-scope spinners.
- `Clerk.Link navigate="sign-in|sign-up|forgot-password"` — cross-flow nav.
- `Clerk.Connection name="google|github|..."` — renders a button that kicks
  off the OAuth redirect. Children are the button content.

Sign-in specific (`SignIn.*`):

- `SignIn.Root` — provides the sign-in state machine context.
- `SignIn.Step name="start|verifications|forgot-password|reset-password|choose-strategy"` —
  only the step matching the current state renders; others are hidden. Use
  `SignIn.Step` like a router.
- `SignIn.Strategy name="password|email_code|phone_code|reset_password_email_code|totp|backup_code"` —
  conditionally renders when that strategy is active; used inside `verifications`
  and `reset-password` steps.
- `SignIn.Action submit|navigate="start|..."|resend` — typed buttons. `submit`
  submits the current step; `resend` asks Clerk to resend a code.
- `SignIn.SupportedStrategy name="..."` — a button that tells Clerk to switch
  strategy (used inside `choose-strategy` step).
- `SignIn.SafeIdentifier` — renders the masked identifier the code was sent to.

Sign-up specific (`SignUp.*`):

- `SignUp.Root`
- `SignUp.Step name="start|continue|verifications"` — `continue` is shown when
  Clerk needs extra fields (e.g. username) it couldn't collect in `start`.
- `SignUp.Strategy name="email_code|phone_code"`
- `SignUp.Action submit|resend`
- `SignUp.Captcha` — mounts Cloudflare Turnstile when bot protection is on.
  Must be present in the sign-up tree or Clerk will error.

### Canonical sign-in hierarchy (what we'll build)

```
<SignIn.Root>
  <SignIn.Step name="start">
    <Clerk.Connection name="google">Continue with Google</Clerk.Connection>
    <Clerk.Connection name="github">Continue with GitHub</Clerk.Connection>
    <divider/>
    <Clerk.Field name="identifier"><Label/><Input type="email"/><FieldError/></Clerk.Field>
    <Clerk.Field name="password"><Label/><Input type="password"/><FieldError/></Clerk.Field>
    <SignIn.Action submit>Sign in</SignIn.Action>
    <SignIn.Action navigate="forgot-password">Forgot password?</SignIn.Action>
    <Clerk.Link navigate="sign-up">Create account</Clerk.Link>
  </SignIn.Step>

  <SignIn.Step name="verifications">
    <SignIn.Strategy name="password">
      <Clerk.Field name="password">.../</Clerk.Field>
      <SignIn.Action submit>Continue</SignIn.Action>
    </SignIn.Strategy>
    <SignIn.Strategy name="email_code">
      <SignIn.SafeIdentifier/>
      <Clerk.Field name="code"><Input type="otp"/></Clerk.Field>
      <SignIn.Action submit>Verify</SignIn.Action>
      <SignIn.Action resend>Resend</SignIn.Action>
    </SignIn.Strategy>
    <SignIn.Strategy name="totp"> ... </SignIn.Strategy>       {/* MFA — later round */}
    <SignIn.Strategy name="backup_code"> ... </SignIn.Strategy>{/* MFA — later round */}
  </SignIn.Step>

  <SignIn.Step name="choose-strategy">
    <SignIn.SupportedStrategy name="email_code">Email me a code</SignIn.SupportedStrategy>
    <SignIn.SupportedStrategy name="password">Use password</SignIn.SupportedStrategy>
  </SignIn.Step>

  <SignIn.Step name="forgot-password">
    <SignIn.SupportedStrategy name="reset_password_email_code">Email code</SignIn.SupportedStrategy>
  </SignIn.Step>

  <SignIn.Step name="reset-password">
    <Clerk.Field name="password">.../</Clerk.Field>
    <Clerk.Field name="confirmPassword">.../</Clerk.Field>
    <SignIn.Action submit>Reset</SignIn.Action>
  </SignIn.Step>
</SignIn.Root>
```

### Canonical sign-up hierarchy

```
<SignUp.Root>
  <SignUp.Step name="start">
    <Clerk.Connection name="google"/>
    <Clerk.Connection name="github"/>
    <Clerk.Field name="emailAddress"><Label/><Input type="email"/><FieldError/></Clerk.Field>
    <Clerk.Field name="password"><Label/><Input type="password"/><FieldError/></Clerk.Field>
    <SignUp.Captcha/>
    <SignUp.Action submit>Create account</SignUp.Action>
    <Clerk.Link navigate="sign-in">Have an account? Sign in</Clerk.Link>
  </SignUp.Step>

  <SignUp.Step name="continue">
    {/* Only shown if extra fields needed */}
    <Clerk.Field name="username">.../</Clerk.Field>
    <SignUp.Action submit>Continue</SignUp.Action>
  </SignUp.Step>

  <SignUp.Step name="verifications">
    <SignUp.Strategy name="email_code">
      <Clerk.Field name="code"><Input type="otp"/></Clerk.Field>
      <SignUp.Action submit>Verify email</SignUp.Action>
      <SignUp.Action resend>Resend</SignUp.Action>
    </SignUp.Strategy>
  </SignUp.Step>
</SignUp.Root>
```

### Routing

`SignIn.Root` / `SignUp.Root` can be given `path="/sign-in"` /
`routing="path"` props. Default is `routing="path"` with the matching
segment. Since we'll drop the `[[...sign-in]]` catch-all, we either:

- keep `routing="path"` and keep catch-all directory (recommended — Clerk
  uses sub-paths like `/sign-in/factor-two`), **OR**
- use `routing="virtual"` and render as a single page (no URL changes per
  step). Simpler for our animated flow.

**Decision for round 1:** Use `routing="virtual"`. Step transitions become
in-page animations — no routing noise, matches terminal-aesthetic overlays.
This means we can collapse `app/sign-in/[[...sign-in]]/page.tsx` to
`app/sign-in/page.tsx`.

## 3. Organizations API

### Dashboard setup (manual, one-time)

In Clerk dashboard → Organizations → Settings:

1. **Enable Organizations**.
2. **Disable "Enable Personal Account"** (toggle OFF). This is the critical
   setting that forces every user to belong to at least one org. Since
   August 2025 this is the default for new apps but our app pre-dates it —
   must be flipped manually.
3. Under "Defaults" → **Allow users to create organizations** = ON.
4. Under Roles → keep the default `admin` and `member` roles.

Flag to user: round 1 changes won't behave correctly until this dashboard
toggle is flipped. The dev-mode keys provided are a fresh tenant so it
should be straightforward; call this out in the PR description.

### Behavior when personal accounts are disabled

- A freshly signed-up user has `auth().sessionClaims` but `auth().orgId`
  is `undefined` until they create/join an org.
- Clerk exposes this as a **pending session**: `useAuth().isSignedIn` is
  `false` and `userId`/`orgId` are `null` until the org is selected.
  (Source: Clerk changelog 2025-08-22.) This is important — it means our
  AuthProvider sees `isSignedIn=false` during the `/onboarding` window.
  Middleware must treat `/onboarding` as reachable for pending sessions.

  Workaround: in middleware, use `auth()` server-side. When personal
  accounts are disabled, `auth()` returns the user but `orgId` is unset.
  Use `userId && !orgId` as the "needs onboarding" signal.

### Hooks

- `useOrganization()` — returns `organization` (active one) + `membership`.
- `useOrganizationList({ userMemberships: true })` — returns
  `{ userMemberships, createOrganization, setActive, isLoaded }`.
  - `userMemberships.data` is the list of orgs the user belongs to.
  - `createOrganization({ name, slug? })` → returns the new `Organization`.
  - `setActive({ organization: org.id })` switches the active org.
- `useUser()` — unchanged from today.
- `useAuth()` — `orgId`, `orgRole`, `orgSlug` available.

### Creating + activating an org (onboarding path)

```ts
const { createOrganization, setActive } = useOrganizationList();
const org = await createOrganization({ name: teamName });
await setActive({ organization: org.id });
router.push("/dashboard");
```

Clerk auto-sets the creator to the `admin` role.

## 4. Middleware — route guard patterns

Our current `middleware.ts` uses `clerkMiddleware()` with `auth.protect()` on
non-public routes. We need to extend it:

```ts
const isPublicRoute = createRouteMatcher(["/sign-in(.*)", "/sign-up(.*)", "/"]);
const isOnboardingRoute = createRouteMatcher(["/onboarding(.*)"]);

middlewareExport = clerkMiddleware(async (auth, req) => {
  const { userId, orgId } = await auth();

  if (!isPublicRoute(req)) {
    if (!userId) {
      // not signed in → Clerk redirects to sign-in
      return (await auth.protect());
    }
    if (!orgId && !isOnboardingRoute(req)) {
      // signed in but no active org → force onboarding
      const url = req.nextUrl.clone();
      url.pathname = "/onboarding";
      return NextResponse.redirect(url);
    }
  }

  const response = NextResponse.next();
  applySecurityHeaders(response, true, req);
  return response;
});
```

Gotchas:

- Must NOT redirect the onboarding route itself to onboarding (infinite loop).
- API routes should bypass the org check or return 401 — we can allowlist
  `/api/clerk/*` and let other API routes 401 via `auth.protect()`.

## 5. Custom Team Switcher (sidebar)

Replace `components/layout/clerk-user-button.tsx` usage in the sidebar
`UserSection` with a custom component built on `useOrganization` +
`useOrganizationList`. We still keep Clerk's `<UserButton>` available for
account/sign-out but nested inside our popover, OR use `useClerk().signOut`
directly. Simpler: use `signOut()` and skip `<UserButton>` entirely.

Popover contents:

- Active team header (name + role).
- Switch team: list of other memberships, click → `setActive`.
- Create team: opens inline form → `createOrganization`.
- Invite members: link to `/settings/team/invites` (future round).
- Separator.
- Account: user email, "Sign out" → `signOut()`.

## 6. MFA / 2FA (round N+1 — not round 1)

Hooks & methods live on `useUser().user`:

- TOTP enroll: `user.createTOTP()` → returns `{ secret, uri, object }`. Show
  QR code built from `uri`. Then `user.verifyTOTP({ code })`.
- SMS 2FA: on a `PhoneNumberResource`,
  `phone.setReservedForSecondFactor({ reserved: true })` + `makeDefaultSecondFactor()`.
- Backup codes: `user.createBackupCode()` → returns list once.
- Sign-in flow: after password submit, Clerk transitions to the
  `verifications` step with `SignIn.Strategy name="totp"` / `backup_code` /
  `phone_code` — we just need those strategy blocks in the sign-in tree.

Wrap dangerous ops with `useReverification()`.

## 7. Enterprise SSO (SAML / OIDC)

Configured entirely in Clerk dashboard (Enterprise Connections section).
Users authenticate through the same `<Clerk.Connection>` or the default
"Sign in with your email" flow (Clerk recognizes the domain and redirects
to the IdP). No app-side code change. Details in `enterprise-connections.md`.

## 8. Password reset flow

Handled by `SignIn.Step name="forgot-password"` + `reset-password` as shown
above. No separate page. Works via `reset_password_email_code` strategy —
Clerk sends a code to the identifier, user types it + new password.

## 9. Key files in our app today (quick map)

- `middleware.ts` — add org-redirect.
- `app/layout.tsx` — already wraps in `ClerkProvider`.
- `app/sign-in/[[...sign-in]]/page.tsx` — replace with custom flow at
  `app/sign-in/page.tsx` (virtual routing).
- `app/sign-up/[[...sign-up]]/page.tsx` — same, → `app/sign-up/page.tsx`.
- `app/onboarding/page.tsx` — currently API-key wizard. Add a preceding
  "create your team" step when `orgId` is missing.
- `lib/clerk-theme.ts` — only applies to Clerk's prebuilt components. Our
  Elements-based flow uses Tailwind directly; we can leave this file alone
  (still used by `<UserButton>` if we keep it) or delete when nothing
  imports it.
- `components/layout/sidebar.tsx` — swap `ClerkUserButton` for `TeamSwitcher`.
- `components/layout/clerk-user-button.tsx` — keep (still usable) or remove
  once `TeamSwitcher` covers sign-out.

## 10. Risks & open questions

1. **Dashboard toggle required.** "Disable personal accounts" must be
   flipped manually. Surface in PR.
2. **Pending session quirk.** `useAuth().isSignedIn === false` during the
   post-signup/pre-org window. Our `AuthProvider` treats `isSignedIn` as
   authoritative; we may need a `hasPendingOrg` flag so the onboarding UI
   can render for a user who is technically "pending".
3. **Captcha.** `SignUp.Captcha` mount is mandatory when Turnstile is
   enabled. Must include or bot protection will reject signups.
4. **Social redirect URLs.** Google/GitHub OAuth redirect URIs must be
   registered in Clerk dashboard (already done for `<SignIn>` prebuilt —
   should carry over for Elements).
5. **Email enumeration.** Clerk handles this correctly by default (generic
   errors). Don't undo in our `Clerk.GlobalError` rendering.
6. **Routing mode.** We picked `routing="virtual"`. Con: no shareable URLs
   for deep steps (e.g. a user bookmarked `/sign-in/factor-two`). Minor.
7. **MFA challenge** needs `SignIn.Strategy name="totp"` etc. present even
   in round 1 tree? No — if MFA isn't enabled on the user yet, Clerk never
   transitions there. Safe to defer.

## 11. Links

- Elements overview — https://clerk.com/docs/customization/elements/overview
- Sign-in example — https://clerk.com/docs/customization/elements/examples/sign-in
- Sign-up example — https://clerk.com/docs/customization/elements/examples/sign-up
- Force orgs — https://clerk.com/docs/guides/force-organizations
- Personal accounts disabled changelog — https://clerk.com/changelog/2025-08-22-personal-accounts-disabled
- TOTP MFA flow — https://clerk.com/docs/custom-flows/manage-totp-based-mfa
- Session tasks — https://clerk.com/docs/guides/configure/session-tasks
