function duplicate(value) {
  return JSON.parse(JSON.stringify(value));
}

function extend(target, ...sources) {
  for (const source of sources) {
    for (const key in source) {
      target[key] = source[key];
    }
  }
  return target;
}

function keys(value) {
  const result = [];
  for (const key in value) {
    result.push(key);
  }
  return result;
}

function toMap(list, selector) {
  return list.reduce((result, item) => {
    const key = selector ? selector(item) : item;
    result[key] = 1;
    return result;
  }, {});
}

function cmp(a, b) {
  const left = a instanceof Date ? Number(a) : a;
  const right = b instanceof Date ? Number(b) : b;
  if ((left < right || left == null) && right != null) {
    return -1;
  }
  if ((left > right || right == null) && left != null) {
    return 1;
  }
  if (Number.isNaN(left) && !Number.isNaN(right)) {
    return -1;
  }
  if (Number.isNaN(right) && !Number.isNaN(left)) {
    return 1;
  }
  return 0;
}

const identity = (value) => value;
const isArray = Array.isArray;
const isBoolean = (value) =>
  value === true ||
  value === false ||
  Object.prototype.toString.call(value) === "[object Boolean]";
const isDate = (value) =>
  Object.prototype.toString.call(value) === "[object Date]";
const isNumber = (value) =>
  typeof value === "number" ||
  Object.prototype.toString.call(value) === "[object Number]";
const isObject = (value) => value === Object(value);
const isString = (value) =>
  typeof value === "string" ||
  Object.prototype.toString.call(value) === "[object String]";
const isValid = (value) => value != null && value === value;
const array = (value) =>
  value == null ? [] : Array.isArray(value) ? value : [value];

module.exports = {
  array,
  cmp,
  duplicate,
  extend,
  identity,
  isArray,
  isBoolean,
  isDate,
  isNumber,
  isObject,
  isString,
  isValid,
  keys,
  toMap,
};
