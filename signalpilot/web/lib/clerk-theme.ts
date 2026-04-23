/**
 * Shared Clerk appearance theme.
 * Imported by ClerkProvider (layout.tsx), SignIn page, and SignUp page.
 * Matches the SignalPilot dark monospace terminal aesthetic.
 */
export const clerkAppearance = {
  variables: {
    colorPrimary: "#00ff88",
    colorBackground: "#0a0a0a",
    colorInputBackground: "#080808",
    colorInputText: "#eeeeee",
    colorText: "#eeeeee",
    colorTextSecondary: "#999999",
    colorDanger: "#ff4444",
    colorSuccess: "#00ff88",
    colorWarning: "#ffaa00",
    borderRadius: "0px",
    fontFamily:
      '"JetBrains Mono", "SF Mono", "Fira Code", ui-monospace, monospace',
  },
  elements: {
    card: {
      backgroundColor: "#0a0a0a",
      border: "1px solid #222222",
      borderRadius: "0px",
    },
    headerTitle: {
      color: "#eeeeee",
      fontFamily: "inherit",
      letterSpacing: "0.1em",
      textTransform: "uppercase" as const,
    },
    headerSubtitle: { color: "#999999" },
    socialButtonsBlockButton: {
      border: "1px solid #222222",
      borderRadius: "0px",
      backgroundColor: "#080808",
    },
    formFieldInput: {
      backgroundColor: "#080808",
      border: "1px solid #222222",
      borderRadius: "0px",
      color: "#eeeeee",
    },
    formButtonPrimary: {
      backgroundColor: "#00ff88",
      color: "#050505",
      borderRadius: "0px",
      fontWeight: "600",
    },
    footerActionLink: { color: "#00ff88" },
    identityPreviewEditButton: { color: "#00ff88" },
    userButtonAvatarBox: { borderRadius: "0px" },
  },
} as const;
