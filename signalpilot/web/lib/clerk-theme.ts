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
    colorNeutral: "#eeeeee",
    colorTextOnPrimaryBackground: "#050505",
  },
  elements: {
    card: {
      backgroundColor: "#0a0a0a",
      border: "1px solid #222222",
      borderRadius: "0px",
      boxShadow: "0 4px 24px rgba(0,0,0,0.5)",
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
      color: "#eeeeee",
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
    // Popover card (user menu dropdown)
    userButtonPopoverCard: {
      backgroundColor: "#0a0a0a",
      border: "1px solid #222222",
      borderRadius: "0px",
      boxShadow: "0 4px 24px rgba(0,0,0,0.5)",
    },
    userButtonPopoverMain: {
      backgroundColor: "#0a0a0a",
    },
    userButtonPopoverActions: {
      backgroundColor: "#0a0a0a",
    },
    userButtonPopoverActionButton: {
      color: "#999999",
      borderRadius: "0px",
    },
    userButtonPopoverActionButtonIcon: {
      color: "#666666",
    },
    userPreviewMainIdentifier: {
      color: "#eeeeee",
    },
    userPreviewSecondaryIdentifier: {
      color: "#666666",
    },
    // Hide Clerk branding and development mode badge
    userButtonPopoverFooter: {
      display: "none",
    },
    footer: {
      display: "none",
    },
    // General popover styling
    popoverBox: {
      backgroundColor: "#0a0a0a",
      border: "1px solid #222222",
      borderRadius: "0px",
    },
    // Menu items hover
    menuButton: {
      color: "#999999",
      borderRadius: "0px",
    },
    menuList: {
      backgroundColor: "#0a0a0a",
      border: "1px solid #222222",
    },
    menuItem: {
      color: "#999999",
    },
    // Avatar
    avatarBox: {
      borderRadius: "0px",
    },
    avatarImage: {
      borderRadius: "0px",
    },
    // Badge (development mode)
    badge: {
      display: "none",
    },
  },
} as const;
