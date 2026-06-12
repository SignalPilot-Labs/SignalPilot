import {
  ChevronDownIcon,
  CodeIcon,
  EyeIcon,
  HammerIcon,
  Loader2Icon,
  PlayIcon,
  SaveIcon,
  TestTubeIcon,
} from "lucide-react";
import React, { useState } from "react";
import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/ui/tooltip";
import type { DbtConsoleTab } from "./types";

interface SqlEditorToolbarProps {
  modelName: string;
  projectName: string | null;
  relativePath: string;
  isDirty: boolean;
  isSaving: boolean;
  onSave: () => void;
  onCompile: () => void;
  onPreview: () => void;
  onRunModel: (args: string[]) => void;
  isRunning: boolean;
  activeConsoleTab: DbtConsoleTab;
  onConsoleTabChange: (tab: DbtConsoleTab) => void;
}

export const SqlEditorToolbar: React.FC<SqlEditorToolbarProps> = ({
  modelName,
  projectName,
  relativePath,
  isDirty,
  isSaving,
  onSave,
  onCompile,
  onPreview,
  onRunModel,
  isRunning,
  activeConsoleTab,
  onConsoleTabChange,
}) => {
  const [showBuildMenu, setShowBuildMenu] = useState(false);

  return (
    <div className="flex items-center justify-between px-4 py-2 border-b border-border shrink-0">
      {/* Left: breadcrumb */}
      <div className="flex items-center gap-2 min-w-0">
        {projectName && (
          <>
            <span className="text-xs text-muted-foreground font-mono">
              {projectName}
            </span>
            <span className="text-muted-foreground text-xs">/</span>
          </>
        )}
        <span className="text-sm font-mono font-medium truncate max-w-md">
          {relativePath}
        </span>
        <span className="text-[10px] font-bold uppercase tracking-widest text-emerald-500 bg-emerald-500/10 px-2 py-0.5 rounded">
          MODEL
        </span>
        {isDirty && (
          <span className="text-[10px] font-bold uppercase tracking-widest text-amber-500 bg-amber-500/10 px-2 py-0.5 rounded">
            Modified
          </span>
        )}
      </div>

      {/* Right: action buttons */}
      <div className="flex items-center gap-1.5">
        {/* Compile */}
        <Tooltip content="Compile — resolve Jinja to SQL">
          <Button
            variant="outline"
            size="sm"
            className="gap-1.5 text-xs h-7"
            disabled={isRunning}
            onClick={() => {
              onCompile();
              onConsoleTabChange("compiled");
            }}
          >
            <CodeIcon size={13} />
            Compile
          </Button>
        </Tooltip>

        {/* Preview */}
        <Tooltip content="Preview — run query and show results">
          <Button
            variant="outline"
            size="sm"
            className="gap-1.5 text-xs h-7"
            disabled={isRunning}
            onClick={() => {
              onPreview();
              onConsoleTabChange("results");
            }}
          >
            {isRunning && activeConsoleTab === "results" ? (
              <Loader2Icon size={13} className="animate-spin" />
            ) : (
              <EyeIcon size={13} />
            )}
            Preview
          </Button>
        </Tooltip>

        {/* Build dropdown */}
        <div className="relative">
          <Tooltip content="Build commands for this model">
            <Button
              variant="outline"
              size="sm"
              className="gap-1 text-xs h-7"
              disabled={isRunning}
              onClick={() => setShowBuildMenu(!showBuildMenu)}
            >
              {isRunning && activeConsoleTab === "logs" ? (
                <Loader2Icon size={13} className="animate-spin" />
              ) : (
                <HammerIcon size={13} />
              )}
              Build
              <ChevronDownIcon size={12} />
            </Button>
          </Tooltip>

          {showBuildMenu && (
            <>
              <div
                className="fixed inset-0 z-40"
                onClick={() => setShowBuildMenu(false)}
              />
              <div className="absolute right-0 top-full mt-1 z-50 bg-background border border-border rounded-lg shadow-lg py-1 min-w-[200px]">
                <BuildMenuItem
                  icon={<PlayIcon size={12} />}
                  label="Run this model"
                  description={`dbt run --select ${modelName}`}
                  onClick={() => {
                    onRunModel(["--select", modelName]);
                    setShowBuildMenu(false);
                    onConsoleTabChange("logs");
                  }}
                />
                <BuildMenuItem
                  icon={<PlayIcon size={12} />}
                  label="Run + upstream"
                  description={`dbt run --select +${modelName}`}
                  onClick={() => {
                    onRunModel(["--select", `+${modelName}`]);
                    setShowBuildMenu(false);
                    onConsoleTabChange("logs");
                  }}
                />
                <BuildMenuItem
                  icon={<PlayIcon size={12} />}
                  label="Run + downstream"
                  description={`dbt run --select ${modelName}+`}
                  onClick={() => {
                    onRunModel(["--select", `${modelName}+`]);
                    setShowBuildMenu(false);
                    onConsoleTabChange("logs");
                  }}
                />
                <div className="border-t border-border my-1" />
                <BuildMenuItem
                  icon={<HammerIcon size={12} />}
                  label="Build (run + test)"
                  description={`dbt build --select ${modelName}`}
                  command="build"
                  onClick={() => {
                    onRunModel(["--select", modelName]);
                    setShowBuildMenu(false);
                    onConsoleTabChange("logs");
                  }}
                />
                <BuildMenuItem
                  icon={<TestTubeIcon size={12} />}
                  label="Test this model"
                  description={`dbt test --select ${modelName}`}
                  onClick={() => {
                    onRunModel(["--select", modelName]);
                    setShowBuildMenu(false);
                    onConsoleTabChange("logs");
                  }}
                />
              </div>
            </>
          )}
        </div>

        <div className="w-px h-5 bg-border mx-1" />

        {/* Save */}
        <Tooltip content="Ctrl+S">
          <Button
            variant={isDirty ? "default" : "outline"}
            size="sm"
            className="gap-1.5 text-xs h-7"
            onClick={onSave}
            disabled={!isDirty || isSaving}
          >
            <SaveIcon size={13} />
            {isSaving ? "Saving..." : "Save"}
          </Button>
        </Tooltip>
      </div>
    </div>
  );
};

const BuildMenuItem: React.FC<{
  icon: React.ReactNode;
  label: string;
  description: string;
  command?: string;
  onClick: () => void;
}> = ({ icon, label, description, onClick }) => (
  <button
    type="button"
    className="w-full flex items-center gap-2 px-3 py-1.5 text-left hover:bg-muted/50 transition-colors cursor-pointer"
    onClick={onClick}
  >
    <span className="text-muted-foreground shrink-0">{icon}</span>
    <div className="flex-1 min-w-0">
      <div className="text-xs font-medium">{label}</div>
      <div className="text-[10px] text-muted-foreground font-mono truncate">
        {description}
      </div>
    </div>
  </button>
);
