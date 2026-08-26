import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

if (!process.env.RADAR_DATA_ROOT || !process.env.RADAR_OUTPUT_ROOT) {
  throw new Error("RADAR_DATA_ROOT and RADAR_OUTPUT_ROOT must be set by radar.ps1 or the environment");
}
const dataRoot = process.env.RADAR_DATA_ROOT.replaceAll("\\", "/");
const outputDir = process.env.RADAR_OUTPUT_ROOT.replaceAll("\\", "/");
const inputPath = `${dataRoot}/evidence_candidates_中文.csv`;
const outputPath = `${outputDir}/evidence_candidates_中文.xlsx`;
const previewPath = `${outputDir}/evidence_candidates_中文_preview.png`;

const csv = await fs.readFile(inputPath, "utf8");
const workbook = await Workbook.fromCSV(csv, { sheetName: "证据候选表" });
const sheet = workbook.worksheets.getItemAt(0);
sheet.name = "证据候选表";
sheet.showGridLines = false;

const used = sheet.getUsedRange();
const rowCount = used.values.length;
const colCount = used.values[0].length;
const endCol = String.fromCharCode(64 + colCount);
const endRow = rowCount;
const tableRange = `A1:${endCol}${endRow}`;

sheet.freezePanes.freezeRows(1);
const header = sheet.getRange(`A1:${endCol}1`);
header.format = {
  fill: "#1F4E78",
  font: { bold: true, color: "#FFFFFF" },
  horizontalAlignment: "center",
  verticalAlignment: "center",
  wrapText: true,
  borders: { preset: "all", style: "thin", color: "#D9E2F3" },
};
header.format.rowHeight = 34;

const body = sheet.getRange(`A2:${endCol}${endRow}`);
body.format = {
  verticalAlignment: "top",
  wrapText: true,
  borders: { preset: "inside", style: "thin", color: "#E6E6E6" },
};
sheet.getRange(`A2:A${endRow}`).format.horizontalAlignment = "center";
sheet.getRange(`H2:I${endRow}`).format.horizontalAlignment = "right";
sheet.getRange(`M2:M${endRow}`).format.horizontalAlignment = "right";
sheet.getRange(`G2:G${endRow}`).format.numberFormat = "yyyy-mm-dd hh:mm";
sheet.getRange(`A2:A${endRow}`).format.columnWidth = 12;
sheet.getRange(`B2:B${endRow}`).format.columnWidth = 20;
sheet.getRange(`C2:C${endRow}`).format.columnWidth = 32;
sheet.getRange(`D2:D${endRow}`).format.columnWidth = 23;
sheet.getRange(`E2:E${endRow}`).format.columnWidth = 14;
sheet.getRange(`F2:F${endRow}`).format.columnWidth = 24;
sheet.getRange(`G2:G${endRow}`).format.columnWidth = 22;
sheet.getRange(`H2:I${endRow}`).format.columnWidth = 10;
sheet.getRange(`J2:J${endRow}`).format.columnWidth = 36;
sheet.getRange(`K2:K${endRow}`).format.columnWidth = 76;
sheet.getRange(`L2:L${endRow}`).format.columnWidth = 55;
sheet.getRange(`M2:M${endRow}`).format.columnWidth = 14;
body.format.rowHeight = 54;
sheet.tables.add(tableRange, true, "EvidenceCandidates");

// Expand the 9 representative posts for which full post text and comments were collected.
const detailDir = `${dataRoot}/details_all`;
const selected = used.values.slice(1).map(row => ({
  id: row[0],
  platform: row[3],
  categories: row[2],
  comments: row[8],
  title: row[9],
  url: row[11]
}));
const chineseNotes = {
  "R-0007": ["免费获得2014 Ram 3500，但需要先更换变速箱", "用户在拖挂需求、车辆里程、变速箱维修成本之间权衡；讨论集中在是否值得买、应选原厂还是加强变速箱。"],
  "R-0010": ["山路露营时变速箱温度过高", "第四代 Cummins 在山路、四驱、低速爬坡时变速箱温度达到约222°F；用户寻求散热、节温器和使用建议。"],
  "R-0011": ["2024 Ram 3500 的改装与调谐咨询", "新用户咨询改装报价、ECM处理和未来 SOTF 调谐的可行性，核心疑虑是成本、兼容性和后续升级路径。"],
  "R-0017": ["LB7 EGR 改装经验分享", "用户分享 LB7 平台 EGR 相关改装的零件、安装过程和调谐要求；可观察配件组合、安装难度和专业服务需求。"],
  "R-0022": ["LLY EFI 调谐与多场景标定需求", "用户计划做 EGR 相关改装、变速箱升级和齿比调整，希望获得拖挂、经济、原厂及性能等多种安全标定。"],
  "R-0023": ["L5P 改装状态不透明，求确认后续方案", "用户购买到疑似已改装车辆，但无法确认具体部件和调谐状态；主要痛点是识别、兼容性、缺件和安装决策。"],
  "R-0032": ["2006 6.0 EGR 改装后需要调谐", "用户已购买套件，正在寻找可靠安装店和调谐方案，担心故障灯及改装后的匹配问题。"],
  "R-0036": ["2005 F350 改装车无法启动并伴随线路受热", "高改装车辆出现无法启动、继电器/电池及线路受热等问题；用户需要系统化排查和可靠售后支持。"],
  "R-0039": ["2006 6.0 EGR 套件品牌选择", "用户询问套件品牌和购买渠道，关注产品可靠性、适配性及社区口碑。"]
};
const chineseTitleFallback = {
  "R-0003":"这两辆柴油皮卡该买哪一辆？", "R-0001":"想买一辆 2006 年 5.9 Mega Cab", "R-0013":"气门室盖里有柴油", "R-0031":"2004.5 LLY 车辆情况", "R-0007":"免费获得 2014 Ram 3500，但要修变速箱", "R-0023":"L5P 改装求助", "R-0017":"LB7 EGR 改装方法", "R-0032":"EGR 改装和调谐器", "R-0036":"车辆无法启动，求助", "R-0010":"变速箱温度过高？", "R-0011":"2024 年车型改装咨询", "R-0002":"请帮忙选择调谐方案", "R-0022":"LLY EFI 调谐", "R-0004":"2022 ECM 求助", "R-0039":"2006 6.0 最佳 EGR 套件", "R-0019":"2013 LML 负载下熄火", "R-0027":"2018 L5P 冒烟与轨压问题", "R-0025":"3.9 万英里 LBZ 的 EGR 改装讨论", "R-0009":"柴油新手：准备改装 2024 6.7", "R-0006":"柴油皮卡新车主求助", "R-0033":"定制燃油碗删除方案？", "R-0030":"EGR 改装与进气加热器", "R-0021":"2005 Chevy Silverado 2500HD LLY 改装/维修记录", "R-0020":"大家给 LBZ 用什么调谐服务？", "R-0014":"第三代 6.7 排气方案", "R-0026":"DEF 喷射器冷却管路（改装）", "R-0028":"2.8 柴油改装后的机油选择", "R-0016":"PCV 重定向软管安装空间太紧", "R-0040":"FICM 调谐", "R-0012":"AlfaOBD 能做什么", "R-0038":"6.0 发动机失火", "R-0005":"Diesel Power Source S300 VGT 使用评价", "R-0034":"2016 F250 6.7 Powerstroke 调谐", "R-0024":"加州 RPO 排放代码，但车辆已不在加州", "R-0018":"Catch Can（集油罐）品牌建议", "R-0041":"没有烟雾机如何检查排气泄漏？7.3", "R-0035":"True American Diesel / 柴油改装套件", "R-0008":"ISX 直通排气管", "R-0037":"柴油改装维修店推荐", "R-0029":"2021 GMC 2.8 Duramax 排放问题", "R-0015":"已做 EGR 改装后的重新刷写/调谐"
};
const detailRows = [["证据编号", "中文品类", "动力平台", "社区", "作者", "发帖时间", "英文标题", "中文标题/概括", "完整正文（英文原文）", "正文中文摘要", "中文业务要点", "原帖链接", "评论数", "已抓取评论数"]];
const commentRows = [["证据编号", "评论层级", "评论作者", "得分", "评论内容（英文原文）", "中文阅读提示"]];
for (const item of selected) {
  const detailFile = (await fs.readdir(detailDir)).find(name => name.startsWith(`${item.id}__`) && name.endsWith(".json"));
  if (!detailFile) continue;
  const records = JSON.parse(await fs.readFile(`${detailDir}/${detailFile}`, "utf8"));
  const post = records.find(r => r.type === "POST") ?? records[0];
  const note = chineseNotes[item.id] ?? [chineseTitleFallback[item.id] ?? "Reddit柴油皮卡改装讨论", `已抓取完整正文和评论；主题为“${chineseTitleFallback[item.id] ?? item.title}”，待业务复核。`];
  const candidate = used.values.find(row => row[0] === item.id);
  const cats = candidate?.[2] ?? item.categories;
  const platform = candidate?.[3] ?? item.platform;
  const community = candidate?.[4] ?? "";
  const author = candidate?.[5] ?? post.author ?? "";
  const time = candidate?.[6] ?? "";
  detailRows.push([item.id, cats, platform, community, author, time, item.title, note[0], post.text ?? "", note[1], `业务提示：${note[1]}`, item.url, item.comments, String(records.filter(r => r.type !== "POST").length)]);
  for (const r of records.filter(r => r.type !== "POST")) {
    commentRows.push([item.id, r.type ?? "", r.author ?? "", r.score ?? "", r.text ?? "", "评论原文保留；可结合正文中文摘要判断需求语境。"]);
  }
}

const clusterDefs = [
  { key: "调谐/ECM/兼容性", re: /tuner|tuning|efi|ecm|ficm|flash|re-flash|tune|calibrat/i, scene: "改装后调谐、ECM/故障码或多工况使用", problem: "用户不确定调谐器、ECM、车型和改装组合是否兼容，担心故障灯或动力模式", solution: "询问社区推荐、购买调谐器或寻找安装店", gap: "缺少按车型/改装清单匹配的清晰方案、安装支持和售后" },
  { key: "EGR/DPF/排放系统改装", re: /egr|dpf|def|delete|emission|regen|exhaust gas/i, scene: "排放系统改装、车辆状态不透明或改装后维护", problem: "用户面对套件选择、缺件、状态确认和改装后故障处理", solution: "购买组合套件、查找教程或咨询改装店", gap: "套件边界、适配状态、安装步骤和后续支持不够清晰" },
  { key: "排气/下降管/泄漏", re: /downpipe|up pipe|straight pipe|exhaust|soot|boost leak|smoke machine/i, scene: "排气升级、增压不足或排气泄漏排查", problem: "用户难以判断管路、泄漏和排气配置对性能/噪声的影响", solution: "更换管路、直通排气或用社区经验排查", gap: "缺少可验证的适配清单、泄漏诊断和一体化安装方案" },
  { key: "热管理/变速箱/拖挂", re: /trans temp|transmission|temperature|towing|tow|load|cool|overheat|68rfe|aisin/i, scene: "拖挂、爬坡、越野或高负载使用", problem: "高负载时变速箱温度、耐久性和动力匹配不确定", solution: "更换/加强变速箱、调整节温器或询问散热方案", gap: "缺少按负载和车型匹配的热管理组合及明确温度判断" },
  { key: "PCV/CCV/油气管理", re: /pcv|ccv|catch can|crankcase|oil mist|reroute|hose/i, scene: "曲轴箱通风重定向、油气分离和软管布置", problem: "软管空间紧、耐热耐油不足或改装后出现冒烟/积油", solution: "更换软管、加集油罐或自制替代方案", gap: "缺少耐热耐油、空间友好且可验证的配套套件" },
  { key: "维修诊断/可靠性", re: /misfir|smok|injector|no start|diesel in|sensor|pump|leak|repair|dies|failure|broken/i, scene: "改装车辆出现故障、失火、冒烟或无法启动", problem: "用户难以定位故障来源，维修成本和改装影响不透明", solution: "更换传感器/喷油器、找维修店或依靠社区排查", gap: "需要针对改装车辆的诊断清单、部件组合和可靠售后" }
];
const personaDefs = [
  { key: "DIY改装/维修型", re: /install|build|parts list|swap|kit|garage|wrench|repair|replace/i, desc: "愿意自己安装、维修或组合部件，重视适配、步骤和零件清单。" },
  { key: "性能与调谐爱好者", re: /power|hp|tuner|tuning|turbo|boost|efi|performance|delete/i, desc: "关注动力、调谐和改装组合，愿意比较方案与品牌。" },
  { key: "拖挂/工作场景用户", re: /tow|towing|trailer|hauling|load|work|camp|mountain/i, desc: "车辆用于拖挂、商用、露营或高负载，关注耐久、温度和可靠性。" },
  { key: "购车/新手决策型", re: /buy|bought|new to diesel|new owner|price|worth|deal|recommend/i, desc: "正在买车或刚接触柴油皮卡，需要降低选择和改装风险。" }
];
const aiReviewRows = [["证据编号", "AI预复核", "相关性置信度", "需求主题", "用户场景", "核心问题", "用户已尝试方案", "潜在产品缺口", "信号分", "证据链接", "人工只需确认"]];
const clusterStats = new Map(clusterDefs.map(d => [d.key, { def: d, ids: [], comments: 0, score: 0, links: [] }]));
const personaStats = new Map(personaDefs.map(d => [d.key, { def: d, ids: [], comments: 0, links: [] }]));
for (const item of selected) {
  const detailFile = (await fs.readdir(detailDir)).find(name => name.startsWith(`${item.id}__`) && name.endsWith(".json"));
  if (!detailFile) continue;
  const records = JSON.parse(await fs.readFile(`${detailDir}/${detailFile}`, "utf8"));
  const post = records.find(r => r.type === "POST") ?? records[0];
  const text = records.map(r => r.text ?? "").join(" ");
  const categoryText = String(item.categories ?? "");
  const defs = [];
  const addDef = key => { const d = clusterDefs.find(x => x.key === key); if (d && !defs.includes(d)) defs.push(d); };
  if (/PCV|CCV/.test(categoryText)) addDef("PCV/CCV/油气管理");
  if (/下降管|排气/.test(categoryText)) addDef("排气/下降管/泄漏");
  if (/调谐/.test(categoryText)) addDef("调谐/ECM/兼容性");
  if (/EGR|DPF|排放/.test(categoryText)) addDef("EGR/DPF/排放系统改装");
  for (const d of clusterDefs) if (d.re.test(text)) addDef(d.key);
  if (!defs.length) defs.push(clusterDefs[clusterDefs.length - 1]);
  const def = defs[0];
  for (const d of defs) { const stat = clusterStats.get(d.key); stat.ids.push(item.id); stat.comments += records.filter(r => r.type !== "POST").length; stat.score += Number(item.comments ?? 0); stat.links.push(item.url); }
  const personas = personaDefs.filter(p => p.re.test(text));
  const chosen = personas.length ? personas.slice(0, 2) : [personaDefs[0]];
  for (const p of chosen) { const ps = personaStats.get(p.key); ps.ids.push(item.id); ps.comments += records.filter(r => r.type !== "POST").length; ps.links.push(item.url); }
  const title = chineseTitleFallback[item.id] ?? item.title;
  const adLike = /shop|service|facebook|instagram|looking for a shop|for sale/i.test(text) && !/problem|help|issue|failure|recommend/i.test(text);
  const confidence = adLike ? "中" : (records.length >= 5 ? "高" : "中");
  const signal = Math.min(100, 35 + Math.min(35, records.filter(r => r.type !== "POST").length) + Math.min(20, Number(item.comments ?? 0)) + (confidence === "高" ? 10 : 0));
  aiReviewRows.push([item.id, adLike ? "相关但可能含广告/服务信息" : "保留为需求候选", confidence, def.key, `${def.scene}；帖子主题：${title}`, def.problem, def.solution, def.gap, signal, item.url, adLike ? "确认是否为真实用户需求而非广告" : "确认是否与具体产品机会相关"]);
}
const opportunityRows = [["机会卡ID", "需求主题", "涉及帖子数", "评论总量", "代表证据", "用户场景", "重复痛点", "现有方案不足", "产品机会方向", "优先级", "下一步验证"]];
let oppNo = 1;
for (const stat of clusterStats.values()) {
  if (!stat.ids.length) continue;
  const d = stat.def;
  const priority = stat.ids.length >= 8 ? "高" : (stat.ids.length >= 4 ? "中" : "观察");
  const next = d.key.includes("排放") ? "先做合规边界和车型适配核验，再访谈/竞品对比" : "抽取3-5位代表用户，核对场景、价格和安装难度";
  opportunityRows.push([`OP-${String(oppNo++).padStart(2, "0")}`, d.key, stat.ids.length, stat.comments, stat.links.slice(0, 5).join("\n"), d.scene, d.problem, d.gap, `开发${d.key}的车型适配组合、安装指引和售后支持`, priority, next]);
}
const personaRows = [["画像ID", "行为型用户画像", "涉及帖子数", "典型行为", "关注点", "代表证据", "使用边界"]];
let personaNo = 1;
for (const ps of personaStats.values()) {
  if (!ps.ids.length) continue;
  personaRows.push([`P-${String(personaNo++).padStart(2, "0")}`, ps.key, ps.ids.length, ps.def.desc, "适配、价格、安装难度、可靠性和售后", ps.links.slice(0, 5).join("\n"), "这是基于公开讨论的行为分组，不等同于真实人口属性或个人身份"]);
}

const full = workbook.worksheets.add("完整帖子");
full.showGridLines = false;
full.getRange(`A1:N${detailRows.length}`).values = detailRows;
full.freezePanes.freezeRows(1);
const fullHeader = full.getRange("A1:N1");
fullHeader.format = { fill: "#1F4E78", font: { bold: true, color: "#FFFFFF" }, horizontalAlignment: "center", verticalAlignment: "center", wrapText: true, borders: { preset: "all", style: "thin", color: "#D9E2F3" } };
fullHeader.format.rowHeight = 34;
full.getRange(`A2:N${detailRows.length}`).format = { verticalAlignment: "top", wrapText: true, borders: { preset: "inside", style: "thin", color: "#E6E6E6" } };
full.getRange(`F2:F${detailRows.length}`).format.numberFormat = "yyyy-mm-dd hh:mm";
full.getRange(`A2:A${detailRows.length}`).format.columnWidth = 12;
full.getRange(`B2:C${detailRows.length}`).format.columnWidth = 24;
full.getRange(`D2:E${detailRows.length}`).format.columnWidth = 20;
full.getRange(`F2:F${detailRows.length}`).format.columnWidth = 20;
full.getRange(`G2:H${detailRows.length}`).format.columnWidth = 32;
full.getRange(`I2:I${detailRows.length}`).format.columnWidth = 90;
full.getRange(`J2:K${detailRows.length}`).format.columnWidth = 55;
full.getRange(`L2:L${detailRows.length}`).format.columnWidth = 55;
full.getRange(`M2:N${detailRows.length}`).format.columnWidth = 14;
full.getRange(`A2:N${detailRows.length}`).format.rowHeight = 110;
full.tables.add(`A1:N${detailRows.length}`, true, "FullPosts");

const comments = workbook.worksheets.add("评论明细");
comments.showGridLines = false;
comments.getRange(`A1:F${commentRows.length}`).values = commentRows;
comments.freezePanes.freezeRows(1);
comments.getRange("A1:F1").format = { fill: "#1F4E78", font: { bold: true, color: "#FFFFFF" }, horizontalAlignment: "center", verticalAlignment: "center", wrapText: true, borders: { preset: "all", style: "thin", color: "#D9E2F3" } };
comments.getRange(`A2:F${commentRows.length}`).format = { verticalAlignment: "top", wrapText: true, borders: { preset: "inside", style: "thin", color: "#E6E6E6" } };
comments.getRange(`A2:A${commentRows.length}`).format.columnWidth = 12;
comments.getRange(`B2:B${commentRows.length}`).format.columnWidth = 12;
comments.getRange(`C2:C${commentRows.length}`).format.columnWidth = 24;
comments.getRange(`D2:D${commentRows.length}`).format.columnWidth = 10;
comments.getRange(`E2:E${commentRows.length}`).format.columnWidth = 100;
comments.getRange(`F2:F${commentRows.length}`).format.columnWidth = 42;
comments.getRange(`A2:F${commentRows.length}`).format.rowHeight = 58;
comments.tables.add(`A1:F${commentRows.length}`, true, "PostComments");

const aiSheet = workbook.worksheets.add("AI预复核");
aiSheet.showGridLines = false;
aiSheet.getRange(`A1:K${aiReviewRows.length}`).values = aiReviewRows;
aiSheet.freezePanes.freezeRows(1);
aiSheet.getRange("A1:K1").format = { fill: "#1F4E78", font: { bold: true, color: "#FFFFFF" }, horizontalAlignment: "center", verticalAlignment: "center", wrapText: true, borders: { preset: "all", style: "thin", color: "#D9E2F3" } };
aiSheet.getRange(`A2:K${aiReviewRows.length}`).format = { verticalAlignment: "top", wrapText: true, borders: { preset: "inside", style: "thin", color: "#E6E6E6" } };
aiSheet.getRange(`A2:A${aiReviewRows.length}`).format.columnWidth = 12;
aiSheet.getRange(`B2:C${aiReviewRows.length}`).format.columnWidth = 18;
aiSheet.getRange(`D2:D${aiReviewRows.length}`).format.columnWidth = 26;
aiSheet.getRange(`E2:H${aiReviewRows.length}`).format.columnWidth = 48;
aiSheet.getRange(`I2:I${aiReviewRows.length}`).format.columnWidth = 10;
aiSheet.getRange(`J2:J${aiReviewRows.length}`).format.columnWidth = 55;
aiSheet.getRange(`K2:K${aiReviewRows.length}`).format.columnWidth = 38;
aiSheet.getRange(`A2:K${aiReviewRows.length}`).format.rowHeight = 78;
aiSheet.tables.add(`A1:K${aiReviewRows.length}`, true, "AIReview");

const oppSheet = workbook.worksheets.add("产品机会卡");
oppSheet.showGridLines = false;
oppSheet.getRange(`A1:K${opportunityRows.length}`).values = opportunityRows;
oppSheet.freezePanes.freezeRows(1);
oppSheet.getRange("A1:K1").format = { fill: "#548235", font: { bold: true, color: "#FFFFFF" }, horizontalAlignment: "center", verticalAlignment: "center", wrapText: true, borders: { preset: "all", style: "thin", color: "#D9EAD3" } };
oppSheet.getRange(`A2:K${opportunityRows.length}`).format = { verticalAlignment: "top", wrapText: true, borders: { preset: "inside", style: "thin", color: "#E6E6E6" } };
oppSheet.getRange(`A2:A${opportunityRows.length}`).format.columnWidth = 12;
oppSheet.getRange(`B2:B${opportunityRows.length}`).format.columnWidth = 28;
oppSheet.getRange(`C2:D${opportunityRows.length}`).format.columnWidth = 12;
oppSheet.getRange(`E2:E${opportunityRows.length}`).format.columnWidth = 60;
oppSheet.getRange(`F2:I${opportunityRows.length}`).format.columnWidth = 42;
oppSheet.getRange(`J2:J${opportunityRows.length}`).format.columnWidth = 12;
oppSheet.getRange(`K2:K${opportunityRows.length}`).format.columnWidth = 45;
oppSheet.getRange(`A2:K${opportunityRows.length}`).format.rowHeight = 90;
oppSheet.tables.add(`A1:K${opportunityRows.length}`, true, "OpportunityCards");

const personaSheet = workbook.worksheets.add("用户画像");
personaSheet.showGridLines = false;
personaSheet.getRange(`A1:G${personaRows.length}`).values = personaRows;
personaSheet.freezePanes.freezeRows(1);
personaSheet.getRange("A1:G1").format = { fill: "#7030A0", font: { bold: true, color: "#FFFFFF" }, horizontalAlignment: "center", verticalAlignment: "center", wrapText: true, borders: { preset: "all", style: "thin", color: "#E4DFEC" } };
personaSheet.getRange(`A2:G${personaRows.length}`).format = { verticalAlignment: "top", wrapText: true, borders: { preset: "inside", style: "thin", color: "#E6E6E6" } };
personaSheet.getRange(`A2:A${personaRows.length}`).format.columnWidth = 12;
personaSheet.getRange(`B2:B${personaRows.length}`).format.columnWidth = 24;
personaSheet.getRange(`C2:C${personaRows.length}`).format.columnWidth = 12;
personaSheet.getRange(`D2:E${personaRows.length}`).format.columnWidth = 52;
personaSheet.getRange(`F2:F${personaRows.length}`).format.columnWidth = 60;
personaSheet.getRange(`G2:G${personaRows.length}`).format.columnWidth = 48;
personaSheet.getRange(`A2:G${personaRows.length}`).format.rowHeight = 72;
personaSheet.tables.add(`A1:G${personaRows.length}`, true, "Personas");

const notes = workbook.worksheets.add("字段说明");
notes.showGridLines = false;
notes.getRange("A1:B1").values = [["字段", "说明"]];
notes.getRange("A2:B8").values = [
  ["处理状态", "候选仅表示关键词初筛通过，仍需业务复核；待复核表示相关性不足或可能是噪音。"],
  ["命中品类", "同一帖子可能命中多个品类，使用中文名称合并展示。"],
  ["动力平台", "Powerstroke、Cummins、Duramax及对应品牌平台。"],
  ["英文标题/正文摘要", "保留Reddit原文，便于回查证据；正式报告再制作中文摘要。"],
  ["原帖链接", "每条证据的原始Reddit链接。"],
  ["搜索命中次数", "同一帖子被不同关键词命中的次数，不等于用户人数。"],
  ["使用建议", "先筛选‘候选，待业务复核’，再读取完整评论和用户公开主页。"],
];
notes.getRange("A1:B1").format = {
  fill: "#1F4E78",
  font: { bold: true, color: "#FFFFFF" },
  horizontalAlignment: "center",
  borders: { preset: "all", style: "thin", color: "#D9E2F3" },
};
notes.getRange("A2:B8").format = {
  verticalAlignment: "top",
  wrapText: true,
  borders: { preset: "inside", style: "thin", color: "#E6E6E6" },
};
notes.getRange("A1:A8").format.columnWidth = 22;
notes.getRange("B1:B8").format.columnWidth = 90;
notes.getRange("A2:B8").format.rowHeight = 42;
notes.freezePanes.freezeRows(1);

await fs.mkdir(outputDir, { recursive: true });
const preview = await workbook.render({ sheetName: "完整帖子", range: "A1:N5", scale: 1, format: "png" });
await fs.writeFile(previewPath, new Uint8Array(await preview.arrayBuffer()));
for (const [name, range, file] of [["AI预复核", "A1:K6", "ai_review_preview.png"], ["产品机会卡", "A1:K8", "opportunity_cards_preview.png"], ["用户画像", "A1:G6", "personas_preview.png"], ["评论明细", "A1:F8", "comments_preview.png"]]) {
  const blob = await workbook.render({ sheetName: name, range, scale: 1, format: "png" });
  await fs.writeFile(`${outputDir}/${file}`, new Uint8Array(await blob.arrayBuffer()));
}
const xlsx = await SpreadsheetFile.exportXlsx(workbook);
await xlsx.save(outputPath);

const check = await workbook.inspect({
  kind: "table",
  sheetId: "证据候选表",
  range: "A1:M6",
  include: "values",
  tableMaxRows: 6,
  tableMaxCols: 13,
  maxChars: 5000,
});
console.log(check.ndjson);
const fullCheck = await workbook.inspect({ kind: "table", sheetId: "完整帖子", range: "A1:N3", include: "values", tableMaxRows: 3, tableMaxCols: 14, maxChars: 5000 });
console.log(fullCheck.ndjson);
const oppCheck = await workbook.inspect({ kind: "table", sheetId: "产品机会卡", range: "A1:K10", include: "values", tableMaxRows: 10, tableMaxCols: 11, maxChars: 5000 });
console.log(oppCheck.ndjson);
console.log(`DETAIL_POSTS ${detailRows.length - 1}`);
console.log(`DETAIL_COMMENTS ${commentRows.length - 1}`);
console.log(`AI_REVIEW ${aiReviewRows.length - 1}`);
console.log(`OPPORTUNITIES ${opportunityRows.length - 1}`);
console.log(`PERSONAS ${personaRows.length - 1}`);
console.log(`EXPORTED ${outputPath}`);
console.log(`PREVIEW ${previewPath}`);
