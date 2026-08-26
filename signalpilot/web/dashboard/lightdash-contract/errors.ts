export class UnsupportedDashboardFeatureError extends Error {
  readonly code = "UNSUPPORTED_DASHBOARD_FEATURE";

  constructor(
    readonly path: string,
    readonly feature: string,
  ) {
    super(`Unsupported dashboard feature '${feature}' at ${path}`);
    this.name = "UnsupportedDashboardFeatureError";
  }
}

export class InvalidDashboardDefinitionError extends Error {
  readonly code = "INVALID_DASHBOARD_DEFINITION";

  constructor(message: string) {
    super(message);
    this.name = "InvalidDashboardDefinitionError";
  }
}
