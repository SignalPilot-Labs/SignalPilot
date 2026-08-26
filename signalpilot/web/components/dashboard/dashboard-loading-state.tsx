import styles from "./dashboard-runtime.module.css";

export function DashboardSpinner({
  size = "medium",
}: {
  size?: "small" | "medium";
}) {
  return (
    <span
      className={`${styles.loadingSpinner} ${size === "small" ? styles.loadingSpinnerSmall : ""}`}
      aria-hidden="true"
    />
  );
}

export function DashboardLoadingState({
  label,
  page = false,
  hideLabel = false,
}: {
  label: string;
  page?: boolean;
  hideLabel?: boolean;
}) {
  return (
    <div
      className={`${styles.loadingState} ${page ? styles.pageLoadingState : ""}`}
      role="status"
      aria-label={hideLabel ? label : undefined}
    >
      <DashboardSpinner />
      {hideLabel ? null : <span>{label}</span>}
    </div>
  );
}
