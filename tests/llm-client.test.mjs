import test from 'node:test';
import assert from 'node:assert/strict';

import { createOpenAiCompatibleAnalyzer, validateEnrichment } from '../src/llm-client.mjs';

test('validateEnrichment accepts merge-safe updates with cited facts', () => {
  const result = validateEnrichment({
    executive_summary: { text: 'LLM enriched summary', evidence_ids: ['ev-1'] },
    seller_verdict: { text: 'LLM verdict', evidence_ids: ['ev-2'] },
    candidate_signals: [
      {
        id: 'protective-headlight-film',
        label: '车灯保护膜方向',
        solution_ideas: ['补充安装辅件'],
        claims: {
          facts: [{ text: '公开样本已出现安装与购买场景。', evidence_ids: ['ev-1'] }],
          inferences: [{ text: '适合作为低风险验证项。', evidence_ids: ['ev-2'] }],
          unknowns: ['制造成本'],
        },
        why_not_done: {
          status: 'inference',
          text: '仍需更多跨社区证据。',
          evidence_ids: ['ev-2'],
        },
      },
    ],
    competitors: [{ name: 'AUXITO', evidence_ids: ['ev-2'] }],
  }, ['ev-1', 'ev-2']);

  assert.equal(result.valid, true);
  assert.deepEqual(result.errors, []);
  assert.equal(result.value.executive_summary.text, 'LLM enriched summary');
  assert.equal(result.value.seller_verdict.text, 'LLM verdict');
  assert.equal(result.value.candidate_signals[0].claims.facts[0].text, '公开样本已出现安装与购买场景。');
});

test('validateEnrichment rejects schema-breaking or rule-breaking fields', () => {
  const result = validateEnrichment({
    opportunities: [
      {
        id: 'led-headlight-bulb-kit',
        opportunity_score: 99,
      },
    ],
    analysis_engine: { active_result: 'llm-enriched' },
  }, ['ev-1']);

  assert.equal(result.valid, false);
  assert.match(result.errors.join('\n'), /additional property|unexpected property/i);
});

test('validateEnrichment rejects uncited facts', () => {
  const result = validateEnrichment({
    opportunities: [
      {
        id: 'led-headlight-bulb-kit',
        claims: {
          facts: [
            { text: '这是一个没有合法引用的事实。', evidence_ids: [] },
          ],
        },
      },
    ],
  }, ['ev-1']);

  assert.equal(result.valid, false);
  assert.match(result.errors.join('\n'), /evidence_ids.*(expected at least 1 items|must cite at least one evidence id)/i);
});

test('validateEnrichment rejects unknown evidence ids', () => {
  const result = validateEnrichment({
    opportunities: [
      {
        id: 'led-headlight-bulb-kit',
        claims: {
          facts: [
            { text: '这是一个引用了未知 evidence 的事实。', evidence_ids: ['invented-id'] },
          ],
        },
      },
    ],
  }, ['ev-1']);

  assert.equal(result.valid, false);
  assert.match(result.errors.join('\n'), /unknown evidence id/i);
});

test('validateEnrichment rejects mixed patches when executive_summary uses the wrong top-level shape', () => {
  const result = validateEnrichment({
    executive_summary: 'legacy uncited summary',
    candidate_signals: [
      {
        id: 'protective-headlight-film',
        label: '车灯保护膜方向',
        claims: {
          facts: [{ text: '公开样本已出现安装与购买场景。', evidence_ids: ['ev-1'] }],
        },
      },
    ],
  }, ['ev-1']);

  assert.equal(result.valid, false);
  assert.match(result.errors.join('\n'), /\$\.executive_summary: expected object/i);
});

test('validateEnrichment rejects top-level cited text without citations', () => {
  const result = validateEnrichment({
    seller_verdict: { text: '缺少引用的结论' },
    candidate_signals: [
      {
        id: 'protective-headlight-film',
        claims: {
          facts: [{ text: '公开样本已出现安装与购买场景。', evidence_ids: ['ev-1'] }],
        },
      },
    ],
  }, ['ev-1']);

  assert.equal(result.valid, false);
  assert.match(result.errors.join('\n'), /\$\.seller_verdict\.evidence_ids: missing required property/i);
});

test('validateEnrichment rejects top-level cited text with unknown evidence ids', () => {
  const result = validateEnrichment({
    executive_summary: { text: '引用了未知 evidence 的总结', evidence_ids: ['invented-id'] },
    candidate_signals: [
      {
        id: 'protective-headlight-film',
        claims: {
          facts: [{ text: '公开样本已出现安装与购买场景。', evidence_ids: ['ev-1'] }],
        },
      },
    ],
  }, ['ev-1']);

  assert.equal(result.valid, false);
  assert.match(result.errors.join('\n'), /\$\.executive_summary\.evidence_ids: unknown evidence id "invented-id"/i);
});

test('OpenAI-compatible analyzer sends tracked json_schema, normalizes the wire model, and merges valid enrichments', async () => {
  let requestedUrl = '';
  let requestedBody = null;
  let requestedTimeoutMs = null;
  const originalTimeout = AbortSignal.timeout;
  AbortSignal.timeout = (ms) => {
    requestedTimeoutMs = ms;
    return Symbol('timeout-signal');
  };

  try {
  const analyzer = createOpenAiCompatibleAnalyzer({
    baseUrl: 'https://example.test/v1',
    apiKey: 'test-key',
    model: 'IGNORED-MODEL-NAME',
    fetchImpl: async (url, options) => {
      requestedUrl = String(url);
      requestedBody = JSON.parse(String(options.body));
      assert.equal(options.headers.Authorization, 'Bearer test-key');
      assert.equal(typeof options.signal, 'symbol');
      return createJsonResponse({
        choices: [{
          message: {
            content: JSON.stringify({
              executive_summary: { text: 'LLM enriched', evidence_ids: ['ev-1'] },
              seller_verdict: { text: 'LLM verdict', evidence_ids: ['ev-2'] },
              candidate_signals: [
                {
                  id: 'protective-headlight-film',
                  label: '车灯保护膜方向',
                  claims: {
                    facts: [{ text: '公开样本已出现购买与安装反馈。', evidence_ids: ['ev-1'] }],
                    inferences: [{ text: '更适合作为先行验证产品。', evidence_ids: ['ev-2'] }],
                    unknowns: ['制造成本'],
                  },
                  why_not_done: {
                    status: 'inference',
                    text: '仍需更多跨社区验证。',
                    evidence_ids: ['ev-2'],
                  },
                },
              ],
            }),
          },
        }],
      });
    },
  });

  const result = await analyzer(ruleAnalysisFixture());

  assert.equal(requestedUrl, 'https://example.test/v1/chat/completions');
  assert.equal(requestedBody.model, 'dsv4pro');
  assert.equal(requestedTimeoutMs, 30000);
  assert.equal(requestedBody.response_format.type, 'json_schema');
  assert.equal(requestedBody.response_format.json_schema.name, 'dsv4pro_enrichment_patch');
  assert.equal(requestedBody.response_format.json_schema.strict, true);
  assert.equal(
    requestedBody.response_format.json_schema.schema.$id,
    'https://example.invalid/schemas/dsv4pro-enrichment.schema.json',
  );
  assert.equal(result.executive_summary, 'LLM enriched');
  assert.equal(result.seller_verdict, 'LLM verdict');
  assert.equal(result.candidate_signals[0].id, 'protective-headlight-film');
  assert.equal(result.candidate_signals[0].label, '车灯保护膜方向');
  assert.equal(result.candidate_signals[0].opportunity_score, 42);
  assert.deepEqual(result.candidate_signals[0].claims.facts, ['公开样本已出现购买与安装反馈。']);
  assert.deepEqual(result.candidate_signals[0].claims.unknowns, ['制造成本']);
  } finally {
    AbortSignal.timeout = originalTimeout;
  }
});

test('OpenAI-compatible analyzer rejects the whole patch when top-level cited text is invalid', async () => {
  let attempts = 0;
  const waits = [];
  const analyzer = createOpenAiCompatibleAnalyzer({
    baseUrl: 'https://example.test/v1',
    apiKey: 'test-key',
    fetchImpl: async () => {
      attempts += 1;
      return createJsonResponse({
        choices: [{
          message: {
            content: JSON.stringify({
              seller_verdict: 'legacy uncited verdict',
              candidate_signals: [
                {
                  id: 'protective-headlight-film',
                  label: '会被错误部分接收的候选方向',
                  claims: {
                    facts: [{ text: '公开样本已出现购买与安装反馈。', evidence_ids: ['ev-1'] }],
                  },
                },
              ],
            }),
          },
        }],
      });
    },
    sleepImpl: async (ms) => {
      waits.push(ms);
    },
  });

  await assert.rejects(
    analyzer(ruleAnalysisFixture()),
    /Invalid DSV4Pro enrichment: .*seller_verdict: expected object/i,
  );

  assert.equal(attempts, 2);
  assert.deepEqual(waits, [30000]);
});

test('OpenAI-compatible analyzer retries once after malformed JSON using the 30-second wait', async () => {
  let attempts = 0;
  const waits = [];
  const analyzer = createOpenAiCompatibleAnalyzer({
    baseUrl: 'https://example.test/v1/chat/completions',
    apiKey: 'test-key',
    fetchImpl: async () => {
      attempts += 1;
      if (attempts === 1) {
        return createJsonResponse({
          choices: [{ message: { content: '{"executive_summary": "broken"' } }],
        });
      }
      return createJsonResponse({
        choices: [{
          message: {
            content: JSON.stringify({ executive_summary: { text: 'Recovered summary', evidence_ids: ['ev-1'] } }),
          },
        }],
      });
    },
    sleepImpl: async (ms) => {
      waits.push(ms);
    },
  });

  const result = await analyzer(ruleAnalysisFixture());

  assert.equal(attempts, 2);
  assert.deepEqual(waits, [30000]);
  assert.equal(result.executive_summary, 'Recovered summary');
});

test('OpenAI-compatible analyzer caps Retry-After at 120 seconds', async () => {
  let attempts = 0;
  const waits = [];
  const analyzer = createOpenAiCompatibleAnalyzer({
    baseUrl: 'https://example.test/v1',
    apiKey: 'test-key',
    fetchImpl: async () => {
      attempts += 1;
      if (attempts === 1) {
        return createErrorResponse(429, 'slow down', { 'retry-after': '300' });
      }
      return createJsonResponse({
        choices: [{
          message: {
            content: JSON.stringify({ seller_verdict: { text: 'Recovered verdict', evidence_ids: ['ev-2'] } }),
          },
        }],
      });
    },
    sleepImpl: async (ms) => {
      waits.push(ms);
    },
  });

  const result = await analyzer(ruleAnalysisFixture());

  assert.equal(attempts, 2);
  assert.deepEqual(waits, [120000]);
  assert.equal(result.seller_verdict, 'Recovered verdict');
});

test('OpenAI-compatible analyzer rejects patches that target unknown rule items', async () => {
  const analyzer = createOpenAiCompatibleAnalyzer({
    baseUrl: 'https://example.test/v1',
    apiKey: 'test-key',
    fetchImpl: async () => createJsonResponse({
      choices: [{
        message: {
          content: JSON.stringify({
            opportunities: [
              {
                id: 'invented-opportunity',
                claims: {
                  facts: [{ text: '不存在的规则项。', evidence_ids: ['ev-1'] }],
                },
              },
            ],
          }),
        },
      }],
    }),
    sleepImpl: async () => {},
  });

  await assert.rejects(
    analyzer(ruleAnalysisFixture()),
    /unknown rules opportunity id/i,
  );
});

function ruleAnalysisFixture() {
  return {
    executive_summary: 'rules summary',
    seller_verdict: 'rules verdict',
    opportunities: [
      {
        id: 'led-headlight-bulb-kit',
        label: 'LED 头灯灯泡套装',
        opportunity_score: 61,
        claims: {
          facts: ['rules fact'],
          inferences: ['rules inference'],
          unknowns: ['制造成本'],
        },
        why_not_done: { status: 'unknown', text: null },
      },
    ],
    candidate_signals: [
      {
        id: 'protective-headlight-film',
        label: '车灯保护膜',
        opportunity_score: 42,
        solution_ideas: ['规则方案'],
        fitment_tags: ['H11'],
        claims: {
          facts: ['rules candidate fact'],
          inferences: ['rules candidate inference'],
          unknowns: ['制造成本'],
        },
        why_not_done: { status: 'unknown', text: null },
      },
    ],
    competitors: [{ name: 'AUXITO', evidence_ids: ['ev-2'] }],
    evidence: [
      { id: 'ev-1', quote_original: 'evidence one' },
      { id: 'ev-2', quote_original: 'evidence two' },
    ],
  };
}

function createJsonResponse(payload) {
  return {
    ok: true,
    status: 200,
    headers: createHeaders({}),
    async json() {
      return payload;
    },
    async text() {
      return JSON.stringify(payload);
    },
  };
}

function createErrorResponse(status, body, headerMap) {
  return {
    ok: false,
    status,
    headers: createHeaders(headerMap),
    async json() {
      throw new Error('error response does not expose json');
    },
    async text() {
      return body;
    },
  };
}

function createHeaders(values) {
  const normalized = new Map(Object.entries(values).map(([key, value]) => [key.toLowerCase(), value]));
  return {
    get(name) {
      return normalized.get(String(name).toLowerCase()) ?? null;
    },
  };
}
