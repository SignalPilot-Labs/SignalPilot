"use client";

import { FiveComponentDashboardFixture } from "~/components/dashboard/five-component-dashboard-fixture";
import { fromLightdashFixture } from "~/dashboard/lightdash-contract";
import fiveComponentsFixture from "~/dashboard/lightdash-contract/fixtures/five-components.json";

const definition = fromLightdashFixture(fiveComponentsFixture);

export default function FiveComponentDashboardFixturePage() {
  return <FiveComponentDashboardFixture definition={definition} />;
}
