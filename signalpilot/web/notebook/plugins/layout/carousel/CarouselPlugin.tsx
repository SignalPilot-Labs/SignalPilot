import React, { type JSX } from "react";
// Turbopack compat: ?inline stripped — raw-loader configured in next.config.ts for these CSS files
import swiperCssNavigation from "swiper/css/navigation";
import swiperCssPagination from "swiper/css/pagination";
import swiperCssScrollbar from "swiper/css/scrollbar";
import swiperCssVirtual from "swiper/css/virtual";
import swiperCss from "swiper/css";
import { z } from "zod";
import slidesCss from "@/components/slides/slides.css";
import swiperSlidesCss from "@/components/slides/swiper-slides.css";
import type {
  IStatelessPlugin,
  IStatelessPluginProps,
} from "../../stateless-plugin";

interface Data {
  index?: string | null;
  height?: string | number | null;
}

export class CarouselPlugin implements IStatelessPlugin<Data> {
  tagName = "sp-carousel";

  validator = z.object({
    index: z.string().nullish(),
    height: z.union([z.string(), z.number()]).nullish(),
  });

  // TODO: Move async when we support async css
  cssStyles = [
    swiperCss,
    swiperCssVirtual,
    swiperCssNavigation,
    swiperCssPagination,
    swiperCssScrollbar,
    slidesCss,
    swiperSlidesCss,
  ];

  render(props: IStatelessPluginProps<Data>): JSX.Element {
    return (
      <LazySlidesComponent {...props.data} wrapAround={true}>
        {props.children}
      </LazySlidesComponent>
    );
  }
}

const LazySlidesComponent = React.lazy(
  () => import("../../../components/slides/swiper-component"),
);
