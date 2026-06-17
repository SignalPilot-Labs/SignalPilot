const {
  array,
  isBoolean,
  isDate,
  isNumber,
  isString,
  isValid,
  keys,
} = require("../util");

const TYPES = "__types__";

const parsers = {
  boolean: (value) =>
    value == null || value === ""
      ? null
      : value === "false"
        ? false
        : Boolean(value),
  integer: (value) => (value == null || value === "" ? null : Number(value)),
  number: (value) => (value == null || value === "" ? null : Number(value)),
  date: (value) => (value == null || value === "" ? null : Date.parse(value)),
  string: (value) => (value == null || value === "" ? null : String(value)),
};

function annotation(data, types) {
  if (!types) {
    return data?.[TYPES] ?? null;
  }
  data[TYPES] = types;
  return data;
}

function infer(values, field) {
  const rows = array(values);
  const getter = accessor(field);
  const candidates = ["boolean", "integer", "number", "date"];

  for (const row of rows) {
    const value = getter ? getter(row) : row;
    if (!isValid(value)) {
      continue;
    }

    for (let index = 0; index < candidates.length; index += 1) {
      if (!matchesType(candidates[index], value)) {
        candidates.splice(index, 1);
        index -= 1;
      }
    }

    if (candidates.length === 0) {
      return "string";
    }
  }

  return candidates[0] ?? "string";
}

function inferAll(data, fields) {
  const rows = array(data);
  const names = fields ?? fieldNames(rows);
  return names.reduce((types, field) => {
    types[field] = infer(rows, fields ? field : bracket(field));
    return types;
  }, {});
}

function all(data, fields) {
  const rows = array(data);
  const names = fields ?? fieldNames(rows);
  return names.reduce((types, field) => {
    types[field] = type(rows, fields ? field : bracket(field));
    return types;
  }, {});
}

function type(values, field) {
  const rows = array(values);
  const getter = accessor(field);

  if (rows[TYPES]) {
    const annotated = getter ? getter(rows[TYPES]) : rows[TYPES];
    if (isString(annotated)) {
      return annotated;
    }
  }

  for (const row of rows) {
    const value = getter ? getter(row) : row;
    if (!isValid(value)) {
      continue;
    }
    if (isDate(value)) {
      return "date";
    }
    if (isNumber(value)) {
      return "number";
    }
    if (isBoolean(value)) {
      return "boolean";
    }
    if (isString(value)) {
      return "string";
    }
  }

  return null;
}

function matchesType(candidate, value) {
  switch (candidate) {
    case "boolean":
      return value === "true" || value === "false" || isBoolean(value);
    case "integer": {
      const number = Number(value);
      return !Number.isNaN(number) && Number.isInteger(number);
    }
    case "number":
      return !Number.isNaN(Number(value)) && !isDate(value);
    case "date":
      return !Number.isNaN(Date.parse(value));
    default:
      return false;
  }
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

function bracket(fieldName) {
  return `[${fieldName}]`;
}

function accessor(field) {
  if (field == null || typeof field === "function") {
    return field;
  }
  const path = parseFieldPath(String(field));
  return (row) => path.reduce((value, part) => value?.[part], row);
}

function parseFieldPath(field) {
  const bracketMatch = field.match(/^\[(.*)\]$/);
  if (bracketMatch) {
    return [bracketMatch[1]];
  }
  return field.split(".");
}

module.exports = Object.assign(type, {
  all,
  annotation,
  infer,
  inferAll,
  parsers,
});
