import { SharedSavedChatReport } from "~/components/reports/chat-report-library";

export default async function SharedReportPage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = await params;
  return <SharedSavedChatReport token={token} />;
}
