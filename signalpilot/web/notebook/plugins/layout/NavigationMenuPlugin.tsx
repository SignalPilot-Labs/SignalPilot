import React, { type JSX, lazy } from "react";
import { z } from "zod";
import type {
  IStatelessPlugin,
  IStatelessPluginProps,
} from "../stateless-plugin";

interface MenuItem {
  label: string;
  href: string;
  description?: string | null;
}

interface MenuItemGroup {
  label: string;
  items: MenuItem[];
}

interface Data {
  /**
   * The labels for each item; raw HTML.
   */
  items: (MenuItem | MenuItemGroup)[];

  /**
   * The orientation of the menu.
   */
  orientation: "horizontal" | "vertical";
}

const LazyNavMenu = lazy(() => import("./navigation-menu-component"));

export class NavigationMenuPlugin implements IStatelessPlugin<Data> {
  tagName = "sp-nav-menu";

  private menuItemValidator = z.object({
    label: z.string(),
    href: z.string(),
    description: z.string().nullish(),
  });

  private menuItemGroupValidator = z.object({
    label: z.string(),
    items: z.array(this.menuItemValidator),
  });

  validator = z.object({
    items: z.array(
      z.union([this.menuItemValidator, this.menuItemGroupValidator]),
    ),
    orientation: z.enum(["horizontal", "vertical"]),
  });

  render(props: IStatelessPluginProps<Data>): JSX.Element {
    return <LazyNavMenu {...props.data} />;
  }
}
