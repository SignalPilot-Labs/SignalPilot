import type React from "react";

export const Header: React.FC<{
  Icon: React.FC<React.SVGProps<SVGSVGElement>>;
  control?: React.ReactNode;
  children: React.ReactNode;
}> = ({ Icon, control, children }) => {
  return (
    <div className="flex items-center justify-between gap-2">
      <h2 className="flex items-center gap-2 text-[11px] font-bold tracking-[0.15em] uppercase text-muted-foreground select-none">
        <Icon className="h-3.5 w-3.5" />
        {children}
      </h2>
      {control}
    </div>
  );
};
