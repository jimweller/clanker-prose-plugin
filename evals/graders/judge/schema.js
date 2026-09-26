'use strict';

const text = { type: 'string', minLength: 1 };

function enumOf(ids) {
  if (!Array.isArray(ids) || ids.length === 0) throw new Error('schema built with no ids in scope');
  return [...new Set(ids)].sort();
}

function findingsSchema(itemProperties, required) {
  return {
    type: 'object',
    properties: {
      findings: {
        type: 'array',
        items: { type: 'object', properties: itemProperties, required, additionalProperties: false },
      },
    },
    required: ['findings'],
    additionalProperties: false,
  };
}

function registerSchema(ids) {
  return findingsSchema({ rule: { type: 'string', enum: enumOf(ids) }, span: text, why: text }, ['rule', 'span', 'why']);
}

function proseSchema(ids) {
  return findingsSchema(
    { kind: { type: 'string', enum: ['violation', 'over-applied'] }, rule: { type: 'string', enum: enumOf(ids) }, span: text, why: text },
    ['kind', 'rule', 'span', 'why'],
  );
}

function correctnessSchema() {
  return {
    type: 'object',
    properties: { verdict: { type: 'string', enum: ['pass', 'fail'] }, reason: text },
    required: ['verdict', 'reason'],
    additionalProperties: false,
  };
}

// Covers only the keywords the three schemas above use. The CLI already validated
// against the same schema; this second pass catches a CLI that stops enforcing it.
function validate(schema, value, at = '$') {
  const errors = [];
  if (schema.type === 'object') {
    if (value === null || typeof value !== 'object' || Array.isArray(value)) return [`${at} is not an object`];
    for (const key of schema.required || []) if (!(key in value)) errors.push(`${at}.${key} is required`);
    for (const [key, v] of Object.entries(value)) {
      const sub = schema.properties && schema.properties[key];
      if (!sub) {
        if (schema.additionalProperties === false) errors.push(`${at}.${key} is not allowed`);
        continue;
      }
      errors.push(...validate(sub, v, `${at}.${key}`));
    }
    return errors;
  }
  if (schema.type === 'array') {
    if (!Array.isArray(value)) return [`${at} is not an array`];
    value.forEach((v, i) => errors.push(...validate(schema.items, v, `${at}[${i}]`)));
    return errors;
  }
  if (schema.type === 'string') {
    if (typeof value !== 'string') return [`${at} is not a string`];
    if (schema.minLength !== undefined && value.length < schema.minLength) errors.push(`${at} is shorter than ${schema.minLength}`);
    if (schema.enum && !schema.enum.includes(value)) errors.push(`${at} ${JSON.stringify(value)} is not in the enum`);
    return errors;
  }
  return [`${at} has unsupported schema type ${schema.type}`];
}

module.exports = { registerSchema, proseSchema, correctnessSchema, validate };
