import { SavedChatReportDetail } from "~/components/reports/chat-report-library";

export default async function SavedReportPage({
  params,
}: {
  params: Promise<{ reportId: string }>;
}) {
  const { reportId } = await params;
  return <SavedChatReportDetail reportId={reportId} />;
}
