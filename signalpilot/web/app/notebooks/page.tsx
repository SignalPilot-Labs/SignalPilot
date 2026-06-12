import { redirect } from "next/navigation";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

export default async function NotebooksRedirect({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  const params = await searchParams;
  const next = new URLSearchParams();
  for (const [key, value] of Object.entries(params ?? {})) {
    if (Array.isArray(value)) {
      for (const item of value) {
        next.append(key, item);
      }
    } else if (value !== undefined) {
      next.set(key, value);
    }
  }
  const qs = next.toString();
  redirect(`/projects${qs ? `?${qs}` : ""}`);
}
