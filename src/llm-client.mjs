import { readFileSync } from 'node:fs';

const DSV4PRO_MODEL = 'dsv4pro';
const DEFAULT_TIMEOUT_MS = 60000;
const DEFAULT_RETRY_DELAY_MS = 30000;
const MAX_RETRY_AFTER_MS = 120000;
const MAX_ATTEMPTS = 2;
const ENRICHMENT_SCHEMA = JSON.parse(
  readFileSync(new URL('../schemas/dsv4pro-enrichment.schema.json', import.meta.url), 'utf8'),
);

export function createOpenAiCompatibleAnalyzer({
  baseUrl,
  apiKey,
  model,
  fetchImpl = fetch,
  timeoutMs = DEFAULT_TIMEOUT_MS,
  sleepImpl = delay,
  env = process.env,
} = {}) {
  const resolvedBaseUrl = baseUrl ?? env.RADAR_LLM_BASE_URL;
  const resolvedApiKey = apiKey ?? env.RADAR_LLM_API_KEY;
  if (!resolvedBaseUrl || !resolvedApiKey) {
    throw new Error('RADAR_LLM_BASE_URL and RADAR_LLM_API_KEY are required for DSV4Pro analysis');
  }

  const endpoint = resolvedBaseUrl.endsWith('/chat/completions')
    ? resolvedBaseUrl
    : `${resolvedBaseUrl.replace(/\/$/, '')}/chat/completions`;

  return async (ruleAnalysis) => {
    const allowedEvidenceIds = uniqueStrings((ruleAnalysis?.evidence ?? []).map((item) => item?.id));
    const compact = {
      ...ruleAnalysis,
      evidence: (ruleAnalysis?.evidence ?? []).slice(0, 60),
    };
    let lastError = null;

    for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt += 1) {
      try {
        const response = await fetchImpl(endpoint, {
          method: 'POST',
          headers: {
            Authorization: `Bearer ${resolvedApiKey}`,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            model: DSV4PRO_MODEL,
            temperature: 0.1,
            response_format: { type: 'json_object' },
            messages: [
              {
                role: 'system',
                content: 'You enrich an automotive-lighting Reddit research JSON. Return a JSON object only. Preserve evidence URLs and fact/inference/unknown boundaries. Do not invent prices, supply-chain facts, demographics, or evidence.',
              },
              {
                role: 'user',
                content: `Improve the Chinese executive summary and opportunity wording without changing the schema or unsupported facts:\n${JSON.stringify(compact)}`,
              },
            ],
          }),
          signal: typeof AbortSignal?.timeout === 'function' ? AbortSignal.timeout(timeoutMs) : undefined,
        });

        if (!response.ok) {
          const body = await response.text();
          throw createHttpError(response.status, body, response.headers);
        }

        const payload = await response.json();
        const content = payload?.choices?.[0]?.message?.content;
        if (!content) throw new Error('DSV4Pro response did not contain message content');

        let parsed;
        try {
          parsed = JSON.parse(content);
        } catch (error) {
          throw new Error(`Invalid DSV4Pro JSON: ${error instanceof Error ? error.message : String(error)}`);
        }

        const validation = validateEnrichment(parsed, allowedEvidenceIds);
        if (!validation.valid) {
          throw new Error(`Invalid DSV4Pro enrichment: ${validation.errors.join('; ')}`);
        }

        return applyEnrichment(ruleAnalysis, validation.value);
      } catch (error) {
        lastError = error;
        if (attempt >= MAX_ATTEMPTS) break;
        await sleepImpl(resolveRetryDelay(error));
      }
    }

    throw lastError ?? new Error('DSV4Pro enrichment failed');
  };
}

export function validateEnrichment(result, allowedEvidenceIds) {
  const errors = validateWithSchema(result, ENRICHMENT_SCHEMA, '$');
  if (errors.length) {
    return { valid: false, errors, value: null };
  }

  const allowedIds = new Set(uniqueStrings(allowedEvidenceIds));
  validateUpdateCollection(result?.opportunities, '$.opportunities', allowedIds, errors);
  validateUpdateCollection(result?.candidate_signals, '$.candidate_signals', allowedIds, errors);

  for (const [index, competitor] of (result?.competitors ?? []).entries()) {
    validateEvidenceIds(competitor.evidence_ids, `$.competitors[${index}].evidence_ids`, allowedIds, errors);
  }

  return {
    valid: errors.length === 0,
    errors,
    value: errors.length === 0 ? structuredClone(result) : null,
  };
}

function validateUpdateCollection(items, path, allowedIds, errors) {
  for (const [index, item] of (items ?? []).entries()) {
    validateClaimBundle(item?.claims, `${path}[${index}].claims`, allowedIds, errors);

    if (item?.why_not_done) {
      const whyPath = `${path}[${index}].why_not_done`;
      const status = item.why_not_done.status;
      if (status === 'unknown') {
        if (item.why_not_done.evidence_ids?.length) {
          errors.push(`${whyPath}.evidence_ids: unknown status must not cite evidence ids`);
        }
      } else {
        if (!String(item.why_not_done.text ?? '').trim()) {
          errors.push(`${whyPath}.text: ${status} why_not_done must include text`);
        }
        validateEvidenceIds(item.why_not_done.evidence_ids, `${whyPath}.evidence_ids`, allowedIds, errors);
      }
    }
  }
}

function validateClaimBundle(claims, path, allowedIds, errors) {
  if (!claims) return;

  for (const [index, claim] of (claims.facts ?? []).entries()) {
    validateEvidenceIds(claim.evidence_ids, `${path}.facts[${index}].evidence_ids`, allowedIds, errors);
  }
  for (const [index, claim] of (claims.inferences ?? []).entries()) {
    validateEvidenceIds(claim.evidence_ids, `${path}.inferences[${index}].evidence_ids`, allowedIds, errors);
  }
}

function validateEvidenceIds(evidenceIds, path, allowedIds, errors) {
  const normalized = uniqueStrings(evidenceIds);
  if (!normalized.length) {
    errors.push(`${path}: must cite at least one evidence id`);
    return;
  }
  for (const evidenceId of normalized) {
    if (!allowedIds.has(evidenceId)) {
      errors.push(`${path}: unknown evidence id "${evidenceId}"`);
    }
  }
}

function applyEnrichment(ruleAnalysis, enrichment) {
  const result = {};

  if (typeof enrichment.executive_summary === 'string') {
    result.executive_summary = enrichment.executive_summary;
  }
  if (typeof enrichment.seller_verdict === 'string') {
    result.seller_verdict = enrichment.seller_verdict;
  }
  if (Array.isArray(enrichment.opportunities)) {
    result.opportunities = mergeRuleCollection(
      ruleAnalysis?.opportunities ?? [],
      enrichment.opportunities,
      'opportunity',
    );
  }
  if (Array.isArray(enrichment.candidate_signals)) {
    result.candidate_signals = mergeRuleCollection(
      ruleAnalysis?.candidate_signals ?? [],
      enrichment.candidate_signals,
      'candidate_signals',
    );
  }
  if (Array.isArray(enrichment.competitors)) {
    result.competitors = mergeCompetitors(ruleAnalysis?.competitors ?? [], enrichment.competitors);
  }

  return result;
}

function mergeRuleCollection(baseItems, updates, label) {
  const updateMap = new Map();
  for (const item of updates) {
    if (!baseItems.some((baseItem) => baseItem?.id === item.id)) {
      throw new Error(`Invalid DSV4Pro enrichment: unknown rules ${label} id "${item.id}"`);
    }
    updateMap.set(item.id, item);
  }

  return baseItems.map((item) => {
    const update = updateMap.get(item.id);
    if (!update) return structuredClone(item);

    const merged = structuredClone(item);
    if (typeof update.label === 'string') merged.label = update.label;
    if (typeof update.verdict === 'string') merged.verdict = update.verdict;
    if (Array.isArray(update.solution_ideas)) merged.solution_ideas = uniqueStrings(update.solution_ideas);
    if (Array.isArray(update.fitment_tags)) merged.fitment_tags = uniqueStrings(update.fitment_tags);
    if (update.claims) {
      merged.claims = {
        facts: update.claims.facts ? update.claims.facts.map((claim) => claim.text) : merged.claims?.facts ?? [],
        inferences: update.claims.inferences ? update.claims.inferences.map((claim) => claim.text) : merged.claims?.inferences ?? [],
        unknowns: update.claims.unknowns ? uniqueStrings(update.claims.unknowns) : merged.claims?.unknowns ?? [],
      };
    }
    if (update.why_not_done) {
      merged.why_not_done = {
        status: update.why_not_done.status,
        text: update.why_not_done.text ?? null,
      };
    }
    return merged;
  });
}

function mergeCompetitors(baseCompetitors, updates) {
  const merged = new Map(baseCompetitors.map((item) => [item.name, { ...item, evidence_ids: uniqueStrings(item.evidence_ids) }]));
  for (const item of updates) {
    merged.set(item.name, {
      name: item.name,
      evidence_ids: uniqueStrings(item.evidence_ids),
    });
  }
  return [...merged.values()];
}

function createHttpError(status, body, headers) {
  const error = new Error(`LLM HTTP ${status}: ${String(body ?? '').slice(0, 240)}`);
  const retryAfterMs = parseRetryAfter(headers?.get?.('retry-after'));
  if (retryAfterMs != null) error.retryAfterMs = retryAfterMs;
  error.status = status;
  return error;
}

function resolveRetryDelay(error) {
  const retryAfterMs = Number(error?.retryAfterMs);
  if (Number.isFinite(retryAfterMs)) {
    return Math.min(Math.max(retryAfterMs, 0), MAX_RETRY_AFTER_MS);
  }
  return DEFAULT_RETRY_DELAY_MS;
}

function parseRetryAfter(value) {
  if (!value) return null;
  const seconds = Number(value);
  if (Number.isFinite(seconds)) return seconds * 1000;

  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) return null;
  return Math.max(timestamp - Date.now(), 0);
}

function validateWithSchema(value, schemaNode, path) {
  if (!schemaNode) return [`${path}: missing schema node`];
  if (schemaNode.$ref) {
    return validateWithSchema(value, resolveSchemaRef(schemaNode.$ref), path);
  }

  const errors = [];

  if (schemaNode.enum && !schemaNode.enum.some((item) => Object.is(item, value))) {
    errors.push(`${path}: expected one of ${schemaNode.enum.join(', ')}`);
    return errors;
  }

  if (schemaNode.type && !matchesType(value, schemaNode.type)) {
    const expected = Array.isArray(schemaNode.type) ? schemaNode.type.join('|') : schemaNode.type;
    errors.push(`${path}: expected ${expected}`);
    return errors;
  }

  if (schemaNode.type === 'object') {
    const required = schemaNode.required ?? [];
    for (const key of required) {
      if (!(key in value)) errors.push(`${path}.${key}: missing required property`);
    }
    if (schemaNode.additionalProperties === false) {
      const allowedKeys = new Set(Object.keys(schemaNode.properties ?? {}));
      for (const key of Object.keys(value)) {
        if (!allowedKeys.has(key)) errors.push(`${path}.${key}: unexpected property`);
      }
    }
    for (const [key, propertySchema] of Object.entries(schemaNode.properties ?? {})) {
      if (key in value) {
        errors.push(...validateWithSchema(value[key], propertySchema, `${path}.${key}`));
      }
    }
    return errors;
  }

  if (schemaNode.type === 'array') {
    if (schemaNode.minItems != null && value.length < schemaNode.minItems) {
      errors.push(`${path}: expected at least ${schemaNode.minItems} items`);
    }
    for (const [index, item] of value.entries()) {
      errors.push(...validateWithSchema(item, schemaNode.items ?? {}, `${path}[${index}]`));
    }
    return errors;
  }

  if (schemaNode.type === 'string') {
    if (schemaNode.minLength != null && value.length < schemaNode.minLength) {
      errors.push(`${path}: expected minLength ${schemaNode.minLength}`);
    }
  }

  return errors;
}

function resolveSchemaRef(ref) {
  if (!ref.startsWith('#/')) {
    throw new Error(`Unsupported schema ref: ${ref}`);
  }
  return ref
    .slice(2)
    .split('/')
    .reduce((node, segment) => node?.[segment], ENRICHMENT_SCHEMA);
}

function matchesType(value, schemaType) {
  const expected = Array.isArray(schemaType) ? schemaType : [schemaType];
  return expected.some((type) => {
    if (type === 'null') return value === null;
    if (type === 'array') return Array.isArray(value);
    if (type === 'object') return value !== null && typeof value === 'object' && !Array.isArray(value);
    return typeof value === type;
  });
}

function uniqueStrings(values) {
  return [...new Set((values ?? []).filter(Boolean).map((value) => String(value)))];
}

function delay(ms) {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}
