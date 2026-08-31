// Report-only, evidence-backed product references. These metrics never affect
// opportunity eligibility and are not sales estimates or market size.
const BRANDS = [
  ['SEALIGHT', ['sealight', 'sealights']], ['AUXITO', ['auxito']],
  ['Sylvania', ['sylvania']], ['LASFIT', ['lasfit']],
  ['AlphaRex', ['alpharex', 'alpha rex']], ['Morimoto', ['morimoto']],
  ['Diode Dynamics', ['diode dynamics']], ['OSRAM', ['osram']],
  ['Philips', ['philips']], ['Baja Designs', ['baja designs']],
  ['Hella', ['hella']], ['Form Lighting', ['form lighting']],
];
// A model is emitted only if the literal phrase occurs near its brand. Unknown
// series stay unknown; sockets/platforms elsewhere in a post are not a SKU.
const SERIES = {
  alpharex: /\b(nova(?:s)?|luxx|pro)(?:[- ]series)?\b/i,
  morimoto: /\b(xb(?:\s+(?:led|evo|hybrid))?|2stroke(?:\s+\d(?:\.\d)?)?|x3b|4banger)\b/i,
  lasfit: /\b(ls\s+plus|la\s+plus|ld\s+plus|t3|t10|laair|ls2)\b/i,
  sylvania: /\b(silverstar(?:\s+(?:ultra|zxe))?|xtravision|zevo)\b/i,
  osram: /\b(night\s*breakers?(?:\s+(?:laser|led|\d{3}))?)\b/i,
  'diode dynamics': /\b(ss3|ssc2|sl1|sl2(?:\s+pro)?|slf)\b/i,
  sealight: /\b(x[1-9][a-z]?|s[1-9][a-z]?|f[1-9][a-z]?)\b/i,
};

const normalize = value => String(value ?? '').toLowerCase().replace(/[^a-z0-9\u4e00-\u9fff]+/g, ' ').trim();
const textOf = row => [row.title, row.body_original ?? row.quote_original].filter(Boolean).join('\n');
const matches = (text, term) => (` ${normalize(text)} `).includes(` ${normalize(term)} `);
const round = number => Math.round(number * 100) / 100;
const eligible = row => row?.id && row.quality?.eligible === true && !row.quality?.hard_exclusion;

function commentWeight(row) {
  if (row.type !== 'comment') return 1;
  const score = row.quality?.quality_score;
  if (typeof score === 'number' && Number.isFinite(score)) return Math.max(0, Math.min(1, score / 100));
  return ({ high: 1, medium: 0.6, low: 0.25 })[row.quality?.quality_band] ?? 0;
}

function uniqueEvidence(rows) {
  const ids = new Set(), content = new Set();
  return rows.filter(row => {
    if (!eligible(row) || ids.has(row.id)) return false;
    ids.add(row.id);
    const key = JSON.stringify([row.type, row.post_id, row.author, normalize(textOf(row))]);
    if (content.has(key)) return false;
    content.add(key);
    return true;
  });
}

function detectCategory(text) {
  if (/\b(fog lights?|fog lamps?|slf)\b/i.test(text)) return 'fog-light';
  if (/\b(tail lights?|taillights?|brake lights?)\b/i.test(text)) return 'tail-brake';
  if (/\b(turn signals?|hyperflash)\b/i.test(text)) return 'turn-signal';
  if (/\b(daytime running|drl)\b/i.test(text)) return 'drl';
  if (/\b(light bars?|ditch lights?|auxiliary lights?)\b/i.test(text)) return 'auxiliary';
  if (/\b(headlights?|headlamps?)\b/i.test(text)) return 'headlight';
  return null;
}

function identifyProducts(row, opportunity, brands, explicitProducts) {
  const text = textOf(row).replace(/https?:\/\/\S+/g, '');
  const clauses = text.split(/[\n.!?]+/).map(x => x.trim()).filter(Boolean);
  const found = new Map();
  for (const product of explicitProducts) {
    if (matches(text, product.name)) found.set(normalize(product.name), { ...product, context: text });
  }
  for (const [brand, aliases] of brands) {
    for (const clause of clauses) {
      if (!aliases.some(alias => matches(clause, alias))) continue;
      if (explicitProducts.some(product => matches(clause, product.name) && aliases.some(alias => matches(product.name, alias)))) continue;
      // Do not turn e.g. a LASFIT floor mat in a long mod list into a bulb.
      if (/\b(floor (?:mats?|liners?)|seat covers?)\b/i.test(clause) && !/\b(bulbs?|headlights?)\b/i.test(clause)) continue;
      const category = detectCategory(clause);
      if (category && opportunity.category && category !== opportunity.category) continue;
      // Limit model attribution to this brand's nearby clause, excluding another brand.
      const brandIndex = aliases.map(alias => clause.toLowerCase().indexOf(alias)).filter(i => i >= 0).sort((a,b) => a-b)[0] ?? 0;
      let local = clause.slice(Math.max(0, brandIndex - 65), brandIndex + brand.length + 100);
      if (brands.some(([other, variants]) => other !== brand && variants.some(alias => matches(local, alias)))) {
        local = clause.slice(brandIndex, brandIndex + brand.length);
      }
      const series = SERIES[brand.toLowerCase()]?.exec(local)?.[0]?.replace(/novas/i, 'NOVA').replace(/[- ]series$/i, '');
      const socket = local.match(/\b(?:H(?:1|3|4|7|8|9|10|11|13|16)|900[4567]|9012|D[1-5][SR])(?:\/(?:H\d+|900[4567]|9012))?\b/i)?.[0];
      const model = [series, socket].filter(Boolean).join(' ').toUpperCase();
      const name = model ? `${brand} ${model}` : `${brand}（型号未识别）`;
      const key = normalize(name);
      const previous = found.get(key);
      found.set(key, { name, brand, identification: model ? 'explicit_model' : 'brand_only',
        context: [previous?.context, clause].filter(Boolean).join('\n') });
    }
  }
  const products = [...found.values()];
  return products.filter(product => product.identification !== 'brand_only'
    || !products.some(other => other.brand === product.brand && other.identification === 'explicit_model'));
}

export function enrichReferenceProducts(analysis, keywordCloud = {}) {
  const corpus = uniqueEvidence(analysis.evidence ?? []);
  const evidenceById = new Map(corpus.map(row => [row.id, row]));
  const terms = [...new Map([
    ...(keywordCloud.terms ?? []).map(x => x.term),
    ...Object.values(analysis.research_keywords ?? {}).flat().filter(x => typeof x === 'string'),
  ].filter(Boolean).map(term => [normalize(term), term])).values()];
  const termTotals = new Map(terms.map(term => [term, corpus.filter(row => matches(textOf(row), term)).reduce((sum, row) => sum + commentWeight(row), 0)]));
  const opportunities = (analysis.opportunities ?? []).map(opportunity => {
    const original = opportunity.reference_product_sources ?? opportunity.reference_products ?? [];
    const extraBrands = [...new Set([
      ...original.map(x => x?.brand),
      ...(opportunity.competitor_signals ?? []).map(x => x.name),
    ].filter(Boolean))].filter(brand => !BRANDS.some(([, aliases]) => aliases.some(x => normalize(x) === normalize(brand))));
    const brands = [...BRANDS, ...extraBrands.map(brand => [brand, [brand.toLowerCase()]])];
    // Legacy generated references often used the whole post title as the name.
    // Preserve supplied product names only if they are not that fallback.
    const explicitProducts = original.filter(product => product?.name && !product.identification
      && !product.name.includes(' · ') && !/讨论提及|未命名/.test(product.name)
      && !(product.evidence_ids ?? []).some(id => normalize(evidenceById.get(id)?.title) === normalize(product.name)));
    const ids = new Set([...(opportunity.evidence_ids ?? []), ...original.flatMap(x => x?.evidence_ids ?? [])]);
    const records = corpus.filter(row => ids.has(row.id));
    const groups = new Map();
    let unresolved = 0;
    for (const row of records) {
      const products = identifyProducts(row, opportunity, brands, explicitProducts);
      if (!products.length) unresolved++;
      for (const product of products) {
        const key = normalize(product.name);
        const group = groups.get(key) ?? { ...product, records: new Map() };
        group.records.set(row.id, { row, context: product.context });
        groups.set(key, group);
      }
    }
    const products = [...groups.values()].map(group => {
      const mentions = [...group.records.values()];
      const rows = mentions.map(x => x.row);
      const posts = rows.filter(row => row.type !== 'comment').length;
      const comments = rows.filter(row => row.type === 'comment');
      const commentSum = comments.reduce((sum,row) => sum + commentWeight(row), 0);
      const score = posts + commentSum;
      const associations = terms.filter(term => !matches(group.name, term) && normalize(term) !== normalize(group.brand)).flatMap(term => {
        const shared = mentions.filter(({ context }) => matches(context, term));
        if (!shared.length) return [];
        const weight = shared.reduce((sum, { row }) => sum + commentWeight(row), 0);
        const total = termTotals.get(term) ?? 0;
        if (weight <= 0) return [];
        return [{ term, score: round(100 * 2 * weight / (score + total)),
          cooccurrence_count: shared.length, weighted_cooccurrence: round(weight),
          evidence_ids: shared.map(x => x.row.id), method: 'quality_weighted_dice' }];
      }).sort((a,b) => b.score - a.score || b.cooccurrence_count - a.cooccurrence_count || a.term.localeCompare(b.term));
      // Prefer repeated support whenever available; retain a labelled single
      // observation for sparse products instead of inventing a strong link.
      const repeated = associations.filter(x => x.cooccurrence_count >= 2);
      const top = (repeated.length ? repeated : associations)[0] ?? null;
      return {
        name: group.name, brand: group.brand ?? null, identification: group.identification ?? 'explicit_name',
        evidence_ids: rows.map(row => row.id), source_url: rows[0]?.url ?? null,
        discussion: { score: round(score), mention_count: rows.length, post_count: posts,
          comment_count: comments.length, weighted_comment_count: round(commentSum),
          formula: 'post_count + sum(comment_quality_score / 100)',
          scope: 'eligible_deduplicated_product_mentions',
          average_comment_quality: comments.length ? round(commentSum / comments.length * 100) : null },
        top_keyword: top,
      };
    }).sort((a,b) => b.discussion.score - a.discussion.score || a.name.localeCompare(b.name));
    return { ...opportunity, reference_product_sources: original, reference_products: products,
      unresolved_reference_mentions: unresolved };
  });
  return { ...analysis, opportunities };
}
