import { Suspense } from "react";
import { ConnectorsPage } from "~/components/connectors/connectors-page";
import { ConnectorsListSkeleton } from "~/components/connectors/connectors-list";

export const metadata = { title: "Connectors" };

/** Connectors: external tool servers the chat agent can use. */
export default function SettingsConnectorsPage() {
  return (
    <Suspense
      fallback={
        <div className="mx-auto max-w-[960px] p-5 sm:p-8">
          <ConnectorsListSkeleton />
        </div>
      }
    >
      <ConnectorsPage />
    </Suspense>
  );
}
