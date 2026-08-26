import { Logger } from "./Logger";

export function retryWithTimeout(
  fn: () => boolean,
  opts: { retries: number; delay: number; initialDelay?: number },
) {
  const { retries, delay, initialDelay = 0 } = opts;

  let attempts = 0;
  const retry = () => {
    if (attempts < retries) {
      try {
        if (fn()) {
          return;
        }
      } catch (error) {
        Logger.error(
          `Error executing function on attempt ${attempts + 1}, retrying`,
          { error },
        );
      }

      attempts++;
      setTimeout(retry, delay);
    }
  };

  if (initialDelay > 0) {
    setTimeout(retry, initialDelay);
  } else {
    retry();
  }
}
