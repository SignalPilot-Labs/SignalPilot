import { DashboardPage } from "~/components/dashboards/dashboard-page";

export const metadata = { title: "Dashboard" };

export default async function PublishedDashboardPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  return <DashboardPage key={slug} idOrSlug={slug} />;
}
