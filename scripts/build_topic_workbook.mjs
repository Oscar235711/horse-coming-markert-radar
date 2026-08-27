/** Build the seven-sheet Excel projection from one canonical analysis JSON. */
import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const [analysisPath, outputPath] = process.argv.slice(2);
if (!analysisPath || !outputPath) {
  throw new Error("Usage: build_topic_workbook.mjs <analysis.json> <output.xlsx>");
}

const analysis = JSON.parse(await fs.readFile(analysisPath, "utf8"));
const topics = Array.isArray(analysis.topics) ? analysis.topics : [];
const sheets = ["运行概览", "社区热点排行", "话题分析卡", "帖子及评论证据", "弱信号观察区", "排除与失败记录", "候选社区与词表建议"];
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
    analysis.generated_at ?? "", values(analysis.communities), topics.filter((topic) => topic.status === "formal").length,
    topics.filter((topic) => topic.status === "weak_signal").length,
    Array.isArray(analysis.excluded_records) ? analysis.excluded_records.length : 0,
    analysis.product_output_label ?? "opportunity hypothesis, not launch conclusion",
  ]], [24, 18, 12, 12, 12, 38]);
  sheet.getRange("A4").format.numberFormat = "yyyy-mm-dd";
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
  title(sheet, "话题分析卡（所有结论均为机会假设）", "L");
  table(sheet, ["话题ID", "中文标签", "English label", "摘要", "痛点", "需求", "当前解决方案", "缺口", "机会假设", "车辆/平台/场景", "标签", "验证问题"], topics.filter((topic) => topic.status === "formal").map((topic) => [
    topic.topic_id, topic.label_zh, topic.label_en, topic.summary, values(topic.pains), values(topic.needs),
    values(topic.current_solutions), values(topic.gaps), values(topic.opportunity_hypotheses),
    [values(topic.vehicles), values(topic.platforms), values(topic.scenarios)].filter(Boolean).join(" / "),
    [values(topic.category_tags), values(topic.brand_tags), values(topic.competitor_tags)].filter(Boolean).join("；"), values(topic.validation_questions),
  ]), [26, 20, 22, 35, 24, 24, 24, 24, 34, 30, 26, 30]);
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

{
  const sheet = workbook.worksheets.getItem("候选社区与词表建议");
  title(sheet, "候选社区与词表建议", "D");
  table(sheet, ["类型", "建议", "依据", "状态"], [["词表", "补充痛点、需求和竞品词", "来自已验证话题标签", "待人工审核"]], [16, 34, 38, 16]);
}

await fs.mkdir(new URL(".", `file:///${outputPath.replaceAll("\\", "/")}`).pathname, { recursive: true }).catch(() => {});
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
