import React, { type PropsWithChildren } from "react";
import { type ConnectionStatus, WebSocketState } from "@/core/websocket/types";
import { Disconnected } from "../Disconnected";

interface Props {
  className?: string;
  connection: ConnectionStatus;
  onForceReconnect: () => void;
}

export const AppHeader: React.FC<PropsWithChildren<Props>> = ({
  connection,
  className,
  children,
  onForceReconnect,
}) => {
  return (
    <div className={className}>
      {children}
      {connection.state === WebSocketState.CLOSED && (
        <Disconnected
          reason={connection.reason}
          canTakeover={connection.canTakeover}
          onForceReconnect={onForceReconnect}
        />
      )}
    </div>
  );
};
