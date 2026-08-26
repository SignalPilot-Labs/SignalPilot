import { openNotebook } from "@/utils/links";

export function openSpNotebook(
  event: Pick<Event, "stopPropagation" | "preventDefault">,
  path: string,
) {
  event.stopPropagation();
  event.preventDefault();
  openNotebook(path);
}
