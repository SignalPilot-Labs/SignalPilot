import React, { PropsWithChildren } from 'react';
import { Emitter } from 'mitt';

interface Props$1 {
    name: string | symbol;
    children: React.ReactNode;
}
declare const Fill: React.FC<Props$1>;

type Name = string | symbol;
interface Fillable {
    name: Name;
    ref: symbol;
    children: React.ReactNode;
}

type SlotzEmitter = Emitter<{
    "fill-mount": {
        fill: Fillable;
    };
    "fill-updated": {
        fill: Fillable;
    };
    "fill-unmount": {
        fill: Pick<Fillable, "ref" | "name">;
    };
}>;
/**
 * Controller for managing Fill components
 */
declare class SlotzController {
    bus: SlotzEmitter;
    mount(fill: Fillable): void;
    unmount(fill: Pick<Fillable, "ref" | "name">): void;
    update(fill: Fillable): void;
}

interface ProviderProps {
    /**
     * Optionally pass a custom controller
     * Useful for using outside of React
     */
    controller?: SlotzController;
}
declare const Provider: React.FC<PropsWithChildren<ProviderProps>>;

interface Props {
    /**
     * The name of the component. Use a symbol if you want to be 100% sure the Slot
     * will only be filled by a component you create
     */
    name: string | symbol;
    /**
     * Props to be applied to the child Element of every fill which has the same name.
     *
     *  If the value is a function, it must have the following signature:
     *    (target: Fill, fills: Fill[]) => void;
     *
     *  This allows you to access props on the fill which invoked the function
     *  by using target.props.something()
     */
    childProps?: {
        [key: string]: any;
    };
    children?: React.ReactNode | ((items: React.ReactNode[]) => React.ReactNode);
}
declare function useSlot(name: string | symbol, childProps?: {
    [key: string]: any;
}): React.ReactNode[];
declare const Slot: React.FC<Props>;

export { Fill, Provider, Slot, SlotzController, useSlot };
