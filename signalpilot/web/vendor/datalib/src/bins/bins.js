const EPSILON = 1e-15;

function bins(options) {
  if (!options) {
    throw new Error("Missing binning options.");
  }

  const maxbins = options.maxbins || 15;
  const base = options.base || 10;
  const div = options.div || [5, 2];
  const minstep = options.minstep || 0;
  const min = Number(options.min);
  const max = Number(options.max);
  const span = Math.max(max - min, 0);
  let step = options.step;

  if (!step) {
    if (options.steps) {
      const index = Math.min(
        options.steps.length - 1,
        bisect(options.steps, span / maxbins),
      );
      step = options.steps[index];
    } else if (span === 0) {
      step = 1;
    } else {
      const logBase = Math.log(base);
      const level = Math.ceil(Math.log(maxbins) / logBase);
      step = Math.max(
        minstep,
        Math.pow(base, Math.round(Math.log(span) / logBase) - level),
      );

      while (Math.ceil(span / step) > maxbins) {
        step *= base;
      }

      for (const divisor of div) {
        const candidate = step / divisor;
        if (candidate >= minstep && span / candidate <= maxbins) {
          step = candidate;
        }
      }
    }
  }

  const precision = step >= 1 ? 0 : Math.ceil(-Math.log10(step)) + 1;
  const eps = Math.pow(base, -precision - 1);
  const start = Math.min(min, Math.floor(min / step + eps) * step);
  const stop = Math.ceil(max / step) * step;

  return {
    start,
    stop,
    step,
    unit: { precision },
    value(value) {
      return step * Math.floor(value / step + EPSILON);
    },
    index(value) {
      return Math.floor((value - start) / step + EPSILON);
    },
  };
}

function bisect(values, target) {
  let lo = 0;
  let hi = values.length;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if (values[mid] < target) {
      lo = mid + 1;
    } else {
      hi = mid;
    }
  }
  return lo;
}

module.exports = bins;
