/** Build the canonical Excel projection from one analysis.json. */
import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const [analysisPath, outputPath] = process.argv.slice(2);
if (!analysisPath || !outputPath) {
  throw new Error("Usage: build_topic_workbook.mjs <analysis.json> <output.xlsx>");
}

const analysis = JSON.parse(await fs.readFile(analysisPath, "utf8"));
const topics = Array.isArray(analysis.topics) ? analysis.topics : [];
const communityLibrary = Array.isArray(analysis.community_library) ? analysis.community_library : (analysis.communities ?? []).map((name) => ({ display_name: name, subreddit: `r/${name}`, community_id: `r/${name}`, platform: "柴油皮卡", status: "approved", aliases: [], include_terms: [], exclude_terms: [] }));
const keywordLibrary = analysis.keyword_library && Array.isArray(analysis.keyword_library.candidates)
  ? analysis.keyword_library.candidates
  : (analysis.keyword_candidates ?? []).map((item, index) => ({
      keyword_id: `kw_demo_${index + 1}`, term_en: item.term ?? "", term_zh: item.term_zh ?? "待翻译",
      keyword_type: item.keyword_type ?? "candidate", community: item.community ?? "", topic_key: item.topic_key ?? "",
      variants: item.variants ?? [], post_count: item.post_count ?? 0, author_count: item.author_count ?? 0,
      source_post_ids: item.source_post_ids ?? [], source_comment_ids: item.source_comment_ids ?? [],
      score: item.discovery_score ?? item.score ?? 0, status: item.status ?? "candidate_review",
    })) ;
const sheets = ["运行概览", "社区库", "话题关键词库", "社区热点排行", "话题分析卡", "帖子及评论证据", "弱信号观察区", "排除与失败记录"];
const workbook = Workbook.create();
for (const name of sheets) workbook.worksheets.add(name);

const titleFormat = { fill: "#17365D", font: { bold: true, color: "#FFFFFF", size: 14 }, horizontalAlignment: "left", verticalAlignment: "center" };
const headerFormat = { fill: "#D9EAF7", font: { bold: true, color: "#17365D" }, wrapText: true, verticalAlignment: "center" };
const bodyFormat = { verticalAlignment: "top", wrapText: true };

function title(sheet, text, lastColumn) {
  const range = sheet.getRange(`A1:${lastColumn}1`);
  range.merge();
  range.values = [[text]];
  range.format = titleFormat;
  range.format.rowHeight = 26;
  sheet.showGridLines = false;
}

function table(sheet, headers, rows, widths) {
  const endColumn = columnName(headers.length);
  sheet.getRange(`A3:${endColumn}3`).values = [headers];
  sheet.getRange(`A3:${endColumn}3`).format = headerFormat;
  sheet.getRange(`A3:${endColumn}3`).format.rowHeight = 30;
  if (rows.length) sheet.getRange(`A4:${endColumn}${rows.length + 3}`).values = rows;
  sheet.getRange(`A4:${endColumn}${Math.max(4, rows.length + 3)}`).format = bodyFormat;
  for (let index = 0; index < widths.length; index += 1) {
    sheet.getRange(`${columnName(index + 1)}:${columnName(index + 1)}`).format.columnWidth = widths[index];
  }
  sheet.getRange(`A3:${endColumn}${Math.max(4, rows.length + 3)}`).format.borders = { preset: "all", style: "thin", color: "#D9E2F3" };
  sheet.freezePanes.freezeRows(3);
}

function values(items) { return Array.isArray(items) ? items.join("；") : ""; }
function objectValue(item, key, fallback = "未知") {
  return item && typeof item === "object" && item[key] !== undefined && item[key] !== null && String(item[key]).trim() !== ""
    ? item[key]
    : fallback;
}
function safeText(value) { return String(value ?? "").replaceAll('"', '""'); }
function urlFormula(url) { return `=HYPERLINK("${safeText(url)}","打开证据")`; }
function columnName(number) {
  let result = "";
  for (let value = number; value > 0; value = Math.floor((value - 1) / 26)) result = String.fromCharCode(65 + ((value - 1) % 26)) + result;
  return result;
}

{
  const sheet = workbook.worksheets.getItem("运行概览");
  title(sheet, "社区机会雷达｜运行概览", "F");
  table(sheet, ["生成时间", "社区", "正式话题", "弱信号", "排除记录", "产品输出定位"], [[
    analysis.generated_at ?? "", values(communityLibrary.map((item) => item.display_name ?? item.subreddit)), topics.filter((topic) => topic.status === "formal").length,
    topics.filter((topic) => topic.status === "weak_signal").length,
    Array.isArray(analysis.excluded_records) ? analysis.excluded_records.length : 0,
    analysis.product_output_label ?? "opportunity hypothesis, not launch conclusion",
  ]], [24, 18, 12, 12, 12, 38]);
  sheet.getRange("A4").format.numberFormat = "yyyy-mm-dd";
}

{
  const sheet = workbook.worksheets.getItem("社区库");
  title(sheet, "社区库（本轮固定四个社区）", "K");
  table(sheet, ["社区ID", "Subreddit", "显示名称", "动力平台", "状态", "别名", "纳入词", "排除词", "社区黑话", "配置版本", "话题数"], communityLibrary.map((item) => [
    item.community_id ?? "", item.subreddit ?? "", item.display_name ?? "", item.platform ?? "", item.status ?? "approved",
    values(item.aliases), values(item.include_terms), values(item.exclude_terms), values(item.slang), item.config_version ?? "",
    item.topic_count ?? topics.filter((topic) => String(topic.community ?? "").toLowerCase() === String(item.display_name ?? "").toLowerCase()).length,
  ]), [24, 20, 20, 18, 14, 28, 34, 30, 30, 22, 10]);
}

{
  const sheet = workbook.worksheets.getItem("话题关键词库");
  title(sheet, "话题关键词库（来源可回溯，候选词需人工确认）", "M");
  table(sheet, ["关键词ID", "英文关键词", "中文翻译", "类型", "社区", "父级话题", "变体", "来源帖子数", "独立作者数", "来源帖子ID", "来源评论ID", "发现分", "状态"], keywordLibrary.map((item) => [
    item.keyword_id ?? "", item.term_en ?? "", item.term_zh ?? "待翻译", item.keyword_type ?? "phrase", item.community ?? "", item.topic_key ?? "",
    values(item.variants), item.post_count ?? 0, item.author_count ?? 0, values(item.source_post_ids), values(item.source_comment_ids), item.score ?? 0, item.status ?? "candidate_review",
  ]), [28, 28, 18, 20, 18, 28, 32, 12, 12, 32, 32, 10, 18]);
}

{
  const sheet = workbook.worksheets.getItem("社区热点排行");
  title(sheet, "社区热点排行", "J");
  const ranked = topics.filter((topic) => topic.status === "formal");
  table(sheet, ["排名", "社区", "话题（中文）", "Topic (English)", "热度", "趋势", "帖子", "作者", "评论者", "置信度"], ranked.map((topic, index) => [
    index + 1, topic.community, topic.label_zh, topic.label_en, topic.heat_score, topic.trend,
    topic.post_count, topic.author_count, topic.commenter_count, topic.confidence,
  ]), [8, 14, 22, 26, 10, 12, 10, 10, 12, 10]);
  sheet.getRange(`E4:E${Math.max(4, ranked.length + 3)}`).format.numberFormat = "0.00";
  sheet.getRange(`J4:J${Math.max(4, ranked.length + 3)}`).format.numberFormat = "0.0%";
}

{
  const sheet = workbook.worksheets.getItem("话题分析卡");
  title(sheet, "话题分析卡（所有结论均为机会假设）", "V");
  table(sheet, ["话题ID", "中文标签", "English label", "摘要", "痛点", "需求", "当前解决方案", "缺口", "机会假设", "机会分", "建议", "Top买家抱怨", "最佳切入角", "需求验证", "卖家视角", "为什么未解决", "制造画像", "车辆/平台/场景", "标签", "验证问题", "支持观点", "反对观点"], topics.filter((topic) => topic.status === "formal").map((topic) => [
    topic.topic_id, topic.label_zh, topic.label_en, topic.summary, values(topic.pains), values(topic.needs),
    values(topic.current_solutions), values(topic.gaps), values(topic.opportunity_hypotheses),
    objectValue(topic, "opportunity_score", 0), objectValue(objectValue(topic, "decision", {}), "label"), objectValue(topic, "top_buyer_complaint"), objectValue(topic, "best_opening_angle"),
    [objectValue(objectValue(topic, "demand_validation", {}), "posts", 0), objectValue(objectValue(topic, "demand_validation", {}), "authors", 0), objectValue(objectValue(topic, "demand_validation", {}), "commenters", 0)].join(" / "),
    objectValue(objectValue(topic, "seller_insight", {}), "positioning_angle"), values(objectValue(objectValue(topic, "why_not_done", {}), "reasons", [])),
    JSON.stringify(objectValue(topic, "manufacturing_profile", {}), null, 0),
    [values(topic.vehicles), values(topic.platforms), values(topic.scenarios)].filter(Boolean).join(" / "),
    [values(topic.category_tags), values(topic.brand_tags), values(topic.competitor_tags)].filter(Boolean).join("；"), values(topic.validation_questions), values(topic.supporting_views), values(topic.opposing_views),
  ]), [26, 20, 22, 35, 24, 24, 24, 24, 34, 10, 14, 28, 30, 20, 30, 28, 36, 30, 26, 30, 30, 30]);
}

{
  const sheet = workbook.worksheets.getItem("帖子及评论证据");
  title(sheet, "帖子及评论证据（英文原文与中文翻译相邻）", "I");
  const evidenceRows = topics.flatMap((topic) => (topic.evidence ?? []).map((item) => [
    topic.topic_id, topic.label_zh, item.evidence_id, item.post_id, item.stance, item.claim_en, item.claim_zh, "", item.url,
  ]));
  table(sheet, ["话题ID", "话题", "证据ID", "帖子ID", "观点", "English evidence", "中文翻译", "可点击链接", "原始URL"], evidenceRows, [26, 20, 24, 20, 12, 38, 30, 14, 46]);
  evidenceRows.forEach((row, index) => { sheet.getRange(`H${index + 4}`).formulas = [[urlFormula(row[8])]]; });
}

{
  const sheet = workbook.worksheets.getItem("弱信号观察区");
  title(sheet, "弱信号观察区", "H");
  const weak = topics.filter((topic) => topic.status === "weak_signal");
  table(sheet, ["话题", "Topic", "帖子", "作者", "评论者", "趋势", "热度", "下一步验证"], weak.map((topic) => [
    topic.label_zh, topic.label_en, topic.post_count, topic.author_count, topic.commenter_count, topic.trend, topic.heat_score, values(topic.validation_questions),
  ]), [22, 26, 10, 10, 12, 12, 10, 36]);
}

{
  const sheet = workbook.worksheets.getItem("排除与失败记录");
  title(sheet, "排除与失败记录", "C");
  table(sheet, ["对象", "原因", "说明"], (analysis.excluded_records ?? []).map((item) => [item.canonical_key ?? "", item.reason ?? "", "未进入机会结论。"]), [30, 24, 42]);
}

await fs.mkdir(new URL(".", `file:///${outputPath.replaceAll("\\", "/")}`).pathname, { recursive: true }).catch(() => {});
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);

// Re-import the actual artifact so an export can fail loudly if its workbook
// structure is unreadable, rather than relying only on the in-memory object.
const imported = await SpreadsheetFile.importXlsx(await FileBlob.load(outputPath));
const inspection = await imported.inspect({ kind: "sheet", include: "id,name" });
const inspectedText = String(inspection?.ndjson ?? inspection ?? "");
for (const name of sheets) {
  if (!inspectedText.includes(name)) throw new Error(`Workbook verification failed: missing sheet ${name}`);
}
