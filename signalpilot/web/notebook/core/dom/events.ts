import type { UIElementId } from "../cells/ids";

export function defineCustomEvent<T extends string>(eventName: T) {
  return <D>() => ({
    TYPE: eventName,
    is(event: Event): event is CustomEvent<D> {
      return event.type === eventName;
    },
    create(init: CustomEventInit<D>) {
      return new CustomEvent(eventName, init);
    },
  });
}

export type ValueType = unknown;

export const SpValueInputEvent = defineCustomEvent("sp-value-input")<{
  value: ValueType;
  element: HTMLElement;
}>();
export type SpValueInputEventType = ReturnType<
  typeof SpValueInputEvent.create
>;

export const SpValueUpdateEvent = defineCustomEvent("sp-value-update")<{
  value: ValueType;
  element: HTMLElement;
}>();
export type SpValueUpdateEventType = ReturnType<
  typeof SpValueUpdateEvent.create
>;

export const SpValueReadyEvent = defineCustomEvent("sp-value-ready")<{
  objectId: UIElementId;
}>();
export type SpValueReadyEventType = ReturnType<
  typeof SpValueReadyEvent.create
>;

export const SpIncomingMessageEvent = defineCustomEvent(
  "sp-incoming-message",
)<{
  objectId: UIElementId;
  message: unknown;
  buffers: readonly DataView[];
}>();
export type SpIncomingMessageEventType = ReturnType<
  typeof SpIncomingMessageEvent.create
>;

/**
 * Create a custom event to communicate a change in value
 *
 * This function should be used by UI elements to tell sp-notebook that
 * their value has changed.
 *
 * We also pass in the UI element that is triggering the change.
 * We cannot simply use `e.target` because of "Event Retargeting"
 * which is a feature of the Shadow DOM, that ensures encapsulation by
 * re-targeting events that are emitted from within a shadow root to
 * the shadow root's host element. We do not want to re-target the event
 * because we want to know which element triggered the event.
 *
 * @param value - the new value of the component
 * @param element - the element that changed
 */
export function createInputEvent(
  value: ValueType,
  element: HTMLElement,
): SpValueInputEventType {
  return SpValueInputEvent.create({
    bubbles: true, // bubble to tell sp-notebook that a value has changed
    composed: true,
    detail: { value: value, element: element },
  });
}

// Augment the global namespace to include the custom events
declare global {
  interface HTMLElementEventMap {
    [SpValueInputEvent.TYPE]: SpValueInputEventType;
    [SpValueUpdateEvent.TYPE]: SpValueUpdateEventType;
    [SpValueReadyEvent.TYPE]: SpValueReadyEventType;
    [SpIncomingMessageEvent.TYPE]: SpIncomingMessageEventType;
  }

  interface DocumentEventMap {
    [SpValueInputEvent.TYPE]: SpValueInputEventType;
    [SpValueUpdateEvent.TYPE]: SpValueUpdateEventType;
    [SpValueReadyEvent.TYPE]: SpValueReadyEventType;
    [SpIncomingMessageEvent.TYPE]: SpIncomingMessageEventType;
  }
}
