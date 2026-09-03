import type { ToastType } from "~/components/ui/toast";
import { userFacingErrorMessage } from "~/lib/api/client";

type ToastFn = (message: string, type?: ToastType) => void;

/**
 * Toast a failed request. Errors that mean nothing to the reader, such as a
 * sandbox's expired session token, stay silent instead of surfacing.
 */
export function toastRequestError(
  toast: ToastFn,
  error: unknown,
  fallback: string,
): void {
  const message = userFacingErrorMessage(error, fallback);
  if (message) toast(message, "error");
}
