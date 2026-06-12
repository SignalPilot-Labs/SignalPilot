import { updateQueryParams } from "@/utils/urls";
import { KnownQueryParams } from "../constants";

/**
 * Remove access_token from the query string.
 */
export function cleanupAuthQueryParams() {
  updateQueryParams((params) => {
    params.delete(KnownQueryParams.accessToken);
  });
}
