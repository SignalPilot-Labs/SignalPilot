import { Suspense } from "react";

import { DashboardsTestHarness } from "~/components/dashboards/dashboards-test-harness";

export const metadata = { title: "Dashboards test harness" };

/**
 * Fixture-driven gallery and detail views for exercising the
 * dashboards UX without a gateway. See the harness for the query switches.
 */
export default function DashboardsTestPage() {
  return (
    <Suspense fallback={null}>
      <DashboardsTestHarness />
    </Suspense>
  );
}
