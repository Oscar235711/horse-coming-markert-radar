export function createOpenAiCompatibleAnalyzer({ baseUrl, apiKey, model, fetchImpl = fetch, timeoutMs = 60000 } = {}) {
  if (!baseUrl || !apiKey || !model) throw new Error('baseUrl, apiKey, and model are required for LLM analysis');
  const endpoint = baseUrl.endsWith('/chat/completions') ? baseUrl : `${baseUrl.replace(/\/$/, '')}/chat/completions`;
  return async (ruleAnalysis) => {
    const compact = {
      ...ruleAnalysis,
      evidence: (ruleAnalysis.evidence ?? []).slice(0, 60),
    };
    const response = await fetchImpl(endpoint, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${apiKey}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        model,
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
      throw new Error(`LLM HTTP ${response.status}: ${body.slice(0, 240)}`);
    }
    const payload = await response.json();
    const content = payload?.choices?.[0]?.message?.content;
    if (!content) throw new Error('LLM response did not contain message content');
    return JSON.parse(content);
  };
}
