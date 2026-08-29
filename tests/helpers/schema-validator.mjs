import fs from 'node:fs/promises';
import path from 'node:path';

export async function validateAgainstSchemaFile(repoRoot, name, value) {
  const schema = JSON.parse(await fs.readFile(path.join(repoRoot, 'schemas', name), 'utf8'));
  return validateWithSchema(value, schema, '$');
}

function validateWithSchema(value, schemaNode, schemaPath) {
  if (!schemaNode) return [`${schemaPath}: missing schema node`];

  const errors = [];
  if (schemaNode.enum && !schemaNode.enum.some((item) => Object.is(item, value))) {
    errors.push(`${schemaPath}: expected one of ${schemaNode.enum.join(', ')}`);
  }

  if (schemaNode.type && !matchesType(value, schemaNode.type)) {
    const expected = Array.isArray(schemaNode.type) ? schemaNode.type.join('|') : schemaNode.type;
    errors.push(`${schemaPath}: expected ${expected}`);
    return errors;
  }

  if (schemaNode.type === 'object') {
    const required = schemaNode.required ?? [];
    for (const key of required) {
      if (!(key in value)) errors.push(`${schemaPath}.${key}: missing required property`);
    }
    if (schemaNode.additionalProperties === false) {
      const knownKeys = new Set(Object.keys(schemaNode.properties ?? {}));
      for (const key of Object.keys(value)) {
        if (!knownKeys.has(key)) errors.push(`${schemaPath}.${key}: additional property not allowed`);
      }
    }
    for (const [key, propertySchema] of Object.entries(schemaNode.properties ?? {})) {
      if (key in value) errors.push(...validateWithSchema(value[key], propertySchema, `${schemaPath}.${key}`));
    }
    return errors;
  }

  if (schemaNode.type === 'array') {
    if (schemaNode.minItems != null && value.length < schemaNode.minItems) {
      errors.push(`${schemaPath}: expected at least ${schemaNode.minItems} items`);
    }
    for (const [index, item] of value.entries()) {
      errors.push(...validateWithSchema(item, schemaNode.items ?? {}, `${schemaPath}[${index}]`));
    }
    return errors;
  }

  if (schemaNode.type === 'string') {
    if (schemaNode.minLength != null && value.length < schemaNode.minLength) {
      errors.push(`${schemaPath}: expected minLength ${schemaNode.minLength}`);
    }
    if (schemaNode.format === 'date-time' && Number.isNaN(Date.parse(value))) {
      errors.push(`${schemaPath}: expected RFC3339 date-time`);
    }
    if (schemaNode.const != null && value !== schemaNode.const) {
      errors.push(`${schemaPath}: expected const ${schemaNode.const}`);
    }
    return errors;
  }

  if (schemaNode.type === 'integer') {
    if (!Number.isInteger(value)) errors.push(`${schemaPath}: expected integer`);
    if (schemaNode.minimum != null && value < schemaNode.minimum) {
      errors.push(`${schemaPath}: expected minimum ${schemaNode.minimum}`);
    }
    if (schemaNode.maximum != null && value > schemaNode.maximum) {
      errors.push(`${schemaPath}: expected maximum ${schemaNode.maximum}`);
    }
    return errors;
  }

  return errors;
}

function matchesType(value, schemaType) {
  const expected = Array.isArray(schemaType) ? schemaType : [schemaType];
  return expected.some((type) => {
    if (type === 'array') return Array.isArray(value);
    if (type === 'integer') return Number.isInteger(value);
    if (type === 'number') return typeof value === 'number' && Number.isFinite(value);
    if (type === 'boolean') return typeof value === 'boolean';
    if (type === 'object') return value !== null && typeof value === 'object' && !Array.isArray(value);
    if (type === 'null') return value === null;
    return typeof value === type;
  });
}
