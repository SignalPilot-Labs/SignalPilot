import React, { createContext, useContext, useEffect, Children, useState } from 'react';
import mitt from 'mitt';

const SlotzContext = createContext(null);

const Fill = (props) => {
  const { controller } = useContext(SlotzContext);
  const ref = React.useRef(Symbol("fill"));
  useEffect(() => {
    controller.mount({
      name: props.name,
      ref: ref.current,
      children: props.children
    });
    return () => {
      controller.unmount({
        name: props.name,
        ref: ref.current
      });
    };
  }, []);
  useEffect(() => {
    controller.update({
      name: props.name,
      ref: ref.current,
      children: props.children
    });
  });
  return null;
};

var __defProp$1 = Object.defineProperty;
var __defNormalProp$1 = (obj, key, value) => key in obj ? __defProp$1(obj, key, { enumerable: true, configurable: true, writable: true, value }) : obj[key] = value;
var __publicField$1 = (obj, key, value) => {
  __defNormalProp$1(obj, typeof key !== "symbol" ? key + "" : key, value);
  return value;
};
const Logger = console;
class Manager {
  constructor(bus) {
    __publicField$1(this, "_bus");
    __publicField$1(this, "_db");
    this._bus = bus;
    this.handleFillMount = this.handleFillMount.bind(this);
    this.handleFillUpdated = this.handleFillUpdated.bind(this);
    this.handleFillUnmount = this.handleFillUnmount.bind(this);
    this._db = {
      byName: /* @__PURE__ */ new Map(),
      byFill: /* @__PURE__ */ new Map()
    };
  }
  mount() {
    this._bus.on("fill-mount", this.handleFillMount);
    this._bus.on("fill-updated", this.handleFillUpdated);
    this._bus.on("fill-unmount", this.handleFillUnmount);
  }
  unmount() {
    this._bus.off("fill-mount", this.handleFillMount);
    this._bus.off("fill-updated", this.handleFillUpdated);
    this._bus.off("fill-unmount", this.handleFillUnmount);
  }
  handleFillMount({ fill }) {
    const children = Children.toArray(fill.children);
    const name = fill.name;
    const component = { fill, children, name };
    const reg = this._db.byName.get(name);
    if (reg) {
      reg.components.push(component);
      reg.listeners.forEach((fn) => fn([...reg.components]));
    } else {
      this._db.byName.set(name, {
        listeners: [],
        components: [component]
      });
    }
    this._db.byFill.set(fill.ref, component);
  }
  handleFillUpdated({ fill }) {
    const component = this._db.byFill.get(fill.ref);
    const newElements = Children.toArray(fill.children);
    if (component) {
      component.children = newElements;
      const reg = this._db.byName.get(component.name);
      if (reg) {
        reg.listeners.forEach((fn) => fn([...reg.components]));
      } else {
        throw new Error("registration was expected to be defined");
      }
    } else {
      Logger.error("[handleFillUpdated] component was expected to be defined");
      return;
    }
  }
  handleFillUnmount({
    fill
  }) {
    const oldComponent = this._db.byFill.get(fill.ref);
    if (!oldComponent) {
      Logger.error("[handleFillUnmount] component was expected to be defined");
      return;
    }
    const name = oldComponent.name;
    const reg = this._db.byName.get(name);
    if (!reg) {
      throw new Error("registration was expected to be defined");
    }
    const components = reg.components;
    reg.components = components.filter((c) => c !== oldComponent);
    this._db.byFill.delete(fill.ref);
    if (reg.listeners.length === 0 && reg.components.length === 0) {
      this._db.byName.delete(name);
    } else {
      reg.listeners.forEach((fn) => fn([...reg.components]));
    }
  }
  /**
   * Triggers once immediately, then each time the components change for a location
   *
   * name: String, fn: (components: Component[]) => void
   */
  onComponentsChange(name, fn) {
    const reg = this._db.byName.get(name);
    if (reg) {
      reg.listeners.push(fn);
      fn(reg.components);
    } else {
      this._db.byName.set(name, {
        listeners: [fn],
        components: []
      });
      fn([]);
    }
  }
  getFillsByName(name) {
    const registration = this._db.byName.get(name);
    if (!registration) {
      return [];
    }
    return registration.components.map((c) => c.fill);
  }
  getChildrenByName(name) {
    const registration = this._db.byName.get(name);
    if (!registration) {
      return [];
    }
    return registration.components.map((component) => component.children).reduce((acc, memo) => acc.concat(memo), []);
  }
  /**
   * Removes previous listener
   *
   * name: String, fn: (components: Component[]) => void
   */
  removeOnComponentsChange(name, fn) {
    const reg = this._db.byName.get(name);
    if (!reg) {
      throw new Error("expected registration to be defined");
    }
    const listeners = reg.listeners;
    listeners.splice(listeners.indexOf(fn), 1);
  }
}

var __defProp = Object.defineProperty;
var __defNormalProp = (obj, key, value) => key in obj ? __defProp(obj, key, { enumerable: true, configurable: true, writable: true, value }) : obj[key] = value;
var __publicField = (obj, key, value) => {
  __defNormalProp(obj, typeof key !== "symbol" ? key + "" : key, value);
  return value;
};
class SlotzController {
  constructor() {
    __publicField(this, "bus", mitt());
  }
  mount(fill) {
    this.bus.emit("fill-mount", { fill });
  }
  unmount(fill) {
    this.bus.emit("fill-unmount", { fill });
  }
  update(fill) {
    this.bus.emit("fill-updated", { fill });
  }
}

function createState(controller) {
  const con = controller || new SlotzController();
  return {
    controller: con,
    manager: new Manager(con.bus)
  };
}
const Provider = ({
  controller,
  children
}) => {
  const [state] = React.useState(() => {
    const res = createState(controller);
    res.manager.mount();
    return res;
  });
  React.useEffect(() => {
    return () => {
      state.manager.unmount();
    };
  }, []);
  return /* @__PURE__ */ React.createElement(SlotzContext.Provider, { value: state }, children);
};

function useSlot(name, childProps) {
  const [components, setComponents] = useState([]);
  const { manager } = useContext(SlotzContext);
  useEffect(() => {
    manager.onComponentsChange(name, setComponents);
    return () => {
      manager.removeOnComponentsChange(name, setComponents);
    };
  }, [name]);
  return components.flatMap((component, index) => {
    const { children } = component;
    return children.map((child, index2) => {
      if (typeof child === "number" || typeof child === "string") {
        throw new Error("Only element children will work here");
      }
      return React.cloneElement(child, {
        key: index.toString() + index2.toString(),
        ...childProps
      });
    });
  });
}
const Slot = (props) => {
  const elements = useSlot(props.name, props.childProps);
  if (typeof props.children === "function") {
    const element = props.children(elements);
    if (React.isValidElement(element) || element === null) {
      return element;
    }
    throw new Error(
      "Slot rendered with function must return a valid React Element."
    );
  }
  return elements;
};

export { Fill, Provider, Slot, SlotzController, useSlot };
