export const Constants = {
  githubPage: "",
  releasesPage: "",
  issuesPage: "",
  feedbackForm: "",
  discordLink: "",
  docsPage: "",
  youtube: "",
  molab: "",
};

export const KnownQueryParams = {
  /**
   * When in read mode, if the code should be shown by default
   */
  showCode: "show-code",
  /**
   * When in read mode, if the code should be hidden by default
   */
  includeCode: "include-code",
  /**
   * Session ID for the current notebook
   */
  sessionId: "session_id",
  /**
   * Kiosk mode. If the editor is running in kiosk mode
   */
  kiosk: "kiosk",
  /**
   * VSCode mode. If the editor is running inside VSCode
   */
  vscode: "vscode",
  /**
   * File path of the current notebook
   */
  filePath: "file",
  /**
   * Project ID (cloud workspace project)
   */
  project: "project",
  /**
   * Branch name (cloud workspace branch)
   */
  branch: "branch",
  /**
   * Access token for the current user
   */
  accessToken: "access_token",
  /**
   * Layout view-as. If the editor is in run-mode, this overrides the current
   * layout view. In edit-mode, can be used to start in present mode.
   */
  viewAs: "view-as",
  /**
   * Show the chrome in edit mode.
   * If true, the chrome will be shown.
   * If false, the chrome will be hidden.
   */
  showChrome: "show-chrome",
};

/**
 * CSS class names used throughout the application
 */
export const CSSClasses = {
  /**
   * Class name for cell output areas
   */
  outputArea: "output-area",
};
