import { getCurrentRegistries } from "@/embed/client-binding";
import { Logger } from "@/utils/Logger";
import {
  SpValueReadyEvent,
  type SpValueReadyEventType,
} from "../dom/events";
import type { UIElementRegistry } from "../dom/uiregistry";
import type { RunRequests } from "../network/types";

/**
 * Manager to track running cells.
 */
export class RuntimeState {
  private hasStarted = false;

  /**
   * Active-client instance. Routes to the currently bound client's registry
   * via the client-binding stack; standalone app uses the module singleton.
   */
  static get INSTANCE(): RuntimeState {
    return getCurrentRegistries().runtimeState;
  }

  /**
   * ObjectIds of UIElements whose values need to be updated in the kernel
   */
  private _sendComponentValues: RunRequests["sendComponentValues"] | undefined;
  private uiElementRegistry: UIElementRegistry;

  constructor(uiElementRegistry: UIElementRegistry) {
    this.uiElementRegistry = uiElementRegistry;
  }

  private get sendComponentValues(): RunRequests["sendComponentValues"] {
    if (!this._sendComponentValues) {
      throw new Error("sendComponentValues is not set");
    }
    return this._sendComponentValues;
  }

  /**
   * Start listening for events from UIElements
   */
  start(sendComponentValues: RunRequests["sendComponentValues"]) {
    if (this.hasStarted) {
      Logger.warn("RuntimeState already started");
      return;
    }
    this._sendComponentValues = sendComponentValues;
    document.addEventListener(
      SpValueReadyEvent.TYPE,
      this.handleReadyEvent,
    );
    this.hasStarted = true;
  }

  /**
   * Stop listening for events from UIElements
   */
  stop() {
    if (!this.hasStarted) {
      Logger.warn("RuntimeState already stopped");
      return;
    }
    document.removeEventListener(
      SpValueReadyEvent.TYPE,
      this.handleReadyEvent,
    );
    this.hasStarted = false;
  }

  private handleReadyEvent = (e: SpValueReadyEventType) => {
    const objectId = e.detail.objectId;
    if (!this.uiElementRegistry.has(objectId)) {
      return;
    }

    const value = this.uiElementRegistry.lookupValue(objectId);
    if (value !== undefined) {
      this.sendComponentValues({
        objectIds: [objectId],
        values: [value],
      }).catch(
        // This happens if the run failed to register (401, 403, network
        // error, etc.) A run may fail if the kernel is restarted or the
        // notebook is closed.
        (error) => {
          Logger.warn(error);
        },
      );
    }
  };
}
