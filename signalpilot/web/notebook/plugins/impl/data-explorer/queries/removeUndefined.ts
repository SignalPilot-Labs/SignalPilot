export function removeUndefined<T>(obj: T): T {
  const ret: T = {} as T;
  for (const key in obj) {
    if (obj[key] !== undefined) {
      ret[key] = obj[key];
    }
  }
  return ret;
}
