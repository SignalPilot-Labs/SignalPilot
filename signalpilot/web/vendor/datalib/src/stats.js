const { cmp, isValid, keys } = require("./util");

function summary(data) {
  const rows = Array.isArray(data) ? data : [];
  return fieldNames(rows).map((field) => summarizeField(rows, field));
}

function unique(values, field, results = []) {
  const seen = new Set();
  for (const value of project(values, field)) {
    const key = valueKey(value);
    if (!seen.has(key)) {
      seen.add(key);
      results.push(value);
    }
  }
  return results;
}

const count = Object.assign(
  (values) => values?.length ?? 0,
  {
    valid(values, field) {
      return project(values, field).filter(isValid).length;
    },
    missing(values, field) {
      return project(values, field).filter((value) => value == null).length;
    },
    distinct(values, field) {
      return new Set(project(values, field).map(valueKey)).size;
    },
    map(values, field) {
      const result = {};
      for (const value of project(values, field)) {
        const key = valueKey(value);
        result[key] = (result[key] ?? 0) + 1;
      }
      return result;
    },
  },
);

function median(values, field) {
  return quantile(sortedValid(values, field), 0.5);
}

function quartile(values, field) {
  const sorted = sortedValid(values, field);
  return [quantile(sorted, 0.25), quantile(sorted, 0.5), quantile(sorted, 0.75)];
}

function quantile(values, fieldOrP, maybeP) {
  const projected = maybeP === undefined ? values : project(values, fieldOrP);
  const p = maybeP === undefined ? fieldOrP : maybeP;
  if (!projected.length) {
    return undefined;
  }
  const h = (projected.length - 1) * p + 1;
  const floor = Math.floor(h);
  const value = Number(projected[floor - 1]);
  const fraction = h - floor;
  return fraction
    ? value + fraction * (Number(projected[floor]) - value)
    : value;
}

function sum(values, field) {
  return project(values, field).reduce((total, value) => {
    return isValid(value) ? total + Number(value) : total;
  }, 0);
}

function mean(values, field) {
  const valid = project(values, field).filter(isValid).map(Number);
  return valid.length ? sum(valid) / valid.length : undefined;
}

function variance(values, field) {
  const valid = project(values, field).filter(isValid).map(Number);
  if (valid.length < 2) {
    return 0;
  }
  const avg = mean(valid);
  return (
    valid.reduce((total, value) => total + (value - avg) ** 2, 0) /
    (valid.length - 1)
  );
}

function stdev(values, field) {
  return Math.sqrt(variance(values, field));
}

function min(values, field) {
  return extent(values, field)[0];
}

function max(values, field) {
  return extent(values, field)[1];
}

function extent(values, field) {
  const valid = project(values, field).filter(isValid);
  if (!valid.length) {
    return [undefined, undefined];
  }
  return valid.reduce(
    ([currentMin, currentMax], value) => [
      cmp(value, currentMin) < 0 ? value : currentMin,
      cmp(value, currentMax) > 0 ? value : currentMax,
    ],
    [valid[0], valid[0]],
  );
}

function summarizeField(rows, field) {
  const values = rows.map((row) => row?.[field]);
  const [minimum, maximum] = extent(values);
  const numericValues = values.map(Number).filter((value) => !Number.isNaN(value));
  const quartiles = quartile(numericValues);

  return {
    field,
    count: rows.length,
    valid: count.valid(values),
    missing: count.missing(values),
    distinct: count.distinct(values),
    unique: count.map(values),
    min: minimum,
    max: maximum,
    mean: mean(values),
    median: median(values),
    q1: quartiles[0],
    q3: quartiles[2],
    stdev: stdev(values),
  };
}

function fieldNames(rows) {
  const names = new Set();
  for (const row of rows) {
    for (const key of keys(row ?? {})) {
      names.add(key);
    }
  }
  return [...names];
}

function sortedValid(values, field) {
  return project(values, field).filter(isValid).sort(cmp);
}

function project(values, field) {
  const rows = Array.isArray(values) ? values : [];
  if (!field) {
    return rows;
  }
  const getter = typeof field === "function" ? field : (row) => row?.[field];
  return rows.map(getter);
}

function valueKey(value) {
  if (value === null) {
    return "null";
  }
  if (value instanceof Date) {
    return value.toISOString();
  }
  return String(value);
}

module.exports = {
  count,
  extent,
  max,
  mean,
  median,
  min,
  quartile,
  quantile,
  stdev,
  sum,
  summary,
  unique,
  variance,
};
