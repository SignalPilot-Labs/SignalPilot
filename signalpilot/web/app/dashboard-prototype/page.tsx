"use client";

import { SignalPilotDashboardPrototype } from "~/components/dashboard/signalpilot-dashboard-prototype";
import { fromLightdashFixture } from "~/dashboard/lightdash-contract";
import prototypeFixture from "~/dashboard/lightdash-contract/fixtures/two-chart-prototype.json";
import { mockDashboardDataSource } from "~/lib/dashboard/mock-dashboard-data-source";

const prototypeDashboard = fromLightdashFixture(prototypeFixture);

export default function DashboardPrototypePage() {
  return (
    <SignalPilotDashboardPrototype
      spec={prototypeDashboard}
      dataSource={mockDashboardDataSource}
      dashboardVersionId="dashboard-version-prototype"
    />
  );
}
