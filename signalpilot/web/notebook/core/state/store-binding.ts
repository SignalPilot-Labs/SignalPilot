import { createStore } from "jotai";

// Avoid circular import — JotaiStore is ReturnType<typeof createStore>.
type JotaiStore = ReturnType<typeof createStore>;

export const _moduleSingleton: JotaiStore = createStore();

let _currentStore: JotaiStore = _moduleSingleton;
const _bindStack: JotaiStore[] = [_moduleSingleton];

export function getCurrentStore(): JotaiStore {
  return _currentStore;
}

export function bindStore(s: JotaiStore): void {
  _bindStack.push(s);
  _currentStore = s;
}

export function unbindStore(s: JotaiStore): void {
  if (_bindStack.length === 0) {
    throw new Error("SignalPilot: unbindStore called on empty bind stack");
  }
  const top = _bindStack[_bindStack.length - 1];
  if (top !== s) {
    throw new Error(
      "SignalPilot: unbindStore called with wrong store — lifecycle bug",
    );
  }
  _bindStack.pop();
  _currentStore = _bindStack[_bindStack.length - 1] ?? _moduleSingleton;
}

