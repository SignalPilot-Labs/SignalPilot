import { DashboardSharedView } from "~/components/dashboards/dashboard-shared-view";

export const metadata = { title: "Shared dashboard" };

/** Public, chrome-less view of a link-visible dashboard (see lib/route-chrome). */
export default async function SharedDashboardPage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = await params;
  return <DashboardSharedView token={token} />;
}
