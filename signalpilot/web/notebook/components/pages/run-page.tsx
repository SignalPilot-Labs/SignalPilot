import { Panel, PanelGroup } from "react-resizable-panels";
import type { AppConfig } from "@/core/config/config-schema";
import { Constants } from "@/core/constants";
import { RunApp } from "@/core/run-app";
import { isStaticNotebook } from "@/core/static/static-state";

import { ContextAwarePanel } from "../editor/chrome/panels/context-aware-panel/context-aware-panel";
import { PanelsWrapper } from "../editor/chrome/wrapper/panels";
import { StaticBanner } from "../static-html/static-banner";

interface Props {
  appConfig: AppConfig;
}

const showWatermark = isStaticNotebook();

const RunPage = (props: Props) => {
  return (
    <PanelsWrapper>
      <PanelGroup direction="horizontal" autoSaveId="sp:chrome:v1:run1">
        <Panel>
          <StaticBanner />
          <RunApp appConfig={props.appConfig} />
          {showWatermark && <Watermark />}
        </Panel>
        <ContextAwarePanel />
      </PanelGroup>
    </PanelsWrapper>
  );
};

const Watermark = () => {
  return (
    <div
      className="fixed bottom-0 right-0 z-50 print:hidden"
      data-testid="watermark"
    >
      <a
        href={Constants.githubPage}
        target="_blank"
        className="text-[11px] font-bold tracking-[0.15em] uppercase transition-colors bg-card hover:bg-[#111111] border-t border-l border-border px-3 py-1 flex items-center gap-2 text-muted-foreground hover:text-foreground"
      >
        <span>SignalPilot</span>
      </a>
    </div>
  );
};

export default RunPage;
