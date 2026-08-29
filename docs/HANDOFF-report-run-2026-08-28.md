# 交接文档：真实 Reddit 报告运行中发现的问题（2026-08-28）

> 给推进 Task 7-10 的 Codex/GPT 的交接说明。
> 日期：2026-08-28 · 分支：`codex/automotive-lighting-reddit-radar`
> 运行环境：Windows + WSL 混合；OpenCLI 通道连 Chrome 的 Reddit 登录态（小号 u/AdhesivenessOk5648）

---

## 0. 运行方式（先看这个）

```bash
# 单轮全量（200帖上限配置）
node scripts/run-radar.mjs \
  --config configs/automotive_lighting_us_full.json \
  --transport opencli \
  --opencli .tools/opencli/node_modules/@jackwener/opencli/dist/src/main.js

# 测试（注意：必须用 glob，`node --test tests/` 会报 MODULE_NOT_FOUND）
node --test "tests/*.test.mjs"
```

OpenCLI 前置条件：Chrome 运行中 + Browser Bridge 扩展已装 + Reddit 已登录。
所有 run 产物在 `.local/runs/<run_id>/`，报告是 `report.html`（自包含离线 HTML）。

---

## 1. 已解决的问题（本轮已修复并提交）

### 1.1 OpenCLI 评论解析 bug（数据为 0 的元凶）
- **现象**：真实跑 OpenCLI 通道，详情 9 帖、评论 0 条。
- **根因**：`createOpenCliAdapter.fetchDetails`（src/radar-pipeline.mjs）按 Reddit 原生格式解析，
  但 OpenCLI `reddit read` 返回的是 `type: "POST"/"L0"/"L1"/"L2"` + `text` 字段，
  **没有 `kind`/`body`/`permalink`/`id`**。旧代码 `row.body || row.type === 'comment'`
  永远匹配不到 → 评论全被丢弃。
- **修复**（commit 03be313）：
  - 识别 `type.startsWith('l')` 的行作为评论，正文取 `row.text`；
  - 评论合成稳定 id：`<post_id>-c<index>`（OpenCLI 不返回评论 id）；
  - 过滤 `[+N more replies]` 折叠占位行（注意**前导空格**：`    [+1 more replies]`，正则要先 trim）；
  - `--expand-more false`：`--expand-more true` 会调 /api/morechildren，Reddit 返回孤儿/缺失节点导致整帖失败。

### 1.2 证据 URL 404（"找不到页面"）
- **现象**：报告里"查看 Reddit 原文"链接打开是 404。
- **根因**：OpenCLI 数据无 `permalink`/`url`，fallback 生成 `https://www.reddit.com/comments/<id>`
  （缺 `/r/<subreddit>/` 段），Reddit 对这种格式返回 404。
- **修复**（commit 03be313 + 数据重建脚本）：
  - fetchDetails 里强制 canonical URL：`https://www.reddit.com/r/<sub>/comments/<post_id>/`；
  - `normalizeComment` 优先用已有 `item.url`（原只认 `item.permalink`）；
  - 旧 run 的 checkpoint 详情文件用 candidates.json 元数据重写。

### 1.3 报告交互增强（用户需求）
- 失败记录改为可折叠 `<details>`（有 N 条时默认收起，0 条默认展开）；
- Audience Map / 词云空数据时显示提示文案（不再空白点阵/裸空态）；
- hash 定位：`report.html#map`、`#keyword-cloud` 等直接打开对应 tab（注意：报告 HTML 是模板字符串，内部 JS 不能再用反引号）。

### 1.4 posts 上限 50 → 200
- **现象**：多轮跑数据 100% 重复（相同查询 Reddit 返回相同结果，posts=50 截断后每轮同一批帖）。
- **根因**：`loadLightingConfig` 硬校验 `posts ≤ 50`（src/radar-core.mjs:16），测试同样断言 ≤50。
- **修复**（commit e17a9ca）：校验和测试改为 ≤200；配置 `automotive_lighting_us_full.json` 设 posts=200、deep_dive_posts=200。
- **注意**：200 帖一轮约 2-3 小时（OpenCLI 逐帖走浏览器）。

---

## 2. 未解决的问题（Task 7-10 需关注）

### 2.1 证据质量门过严 → 正式机会恒为 0（最高优先级，建议 Task 8 一起评估）
- **现象**：50 帖 787 评论 → 894 条证据，质量分布：
  `high: 2, medium: 24, weak: 101, noise: 767`，**eligible 仅 25 条** → opportunities=0，candidate_signals=6。
- **原因**：`classifyEvidence`（src/evidence-quality.mjs）对 Reddit 真实短评论过严：
  - `uncertain_geography` 惩罚 -5：712/894 条地理未知（OpenCLI 数据本身不含地理信号，评论里极少提到州名）；
  - `low_information_density` 惩罚 -5：短评论 token ≤6 就被判低信息；
  - 合格线 50 分，双惩罚下大部分评论到不了。
- **影响**：机会引擎（Task 2）和作者深挖（Task 3）都依赖 eligible 证据 → 连锁为空。
  - `selectAuthors` 要求 qualified evidence → author_candidates=0；
  - `selectRoundTwoTerms` 要求 discovery_score≥60 且 ≥2 用户/2 社区 → round_two_terms=0；
  - `buildPersonas` 要求 200 合格证据 → persona_status=insufficient_sample。
- **建议**：Task 8 做 DSV4Pro 校验回退时，一并评估是否调整 quality 阈值/地理惩罚，
  或让 LLM 补充地理/相关性判断（这正是 Task 8 的定位）。当前"规则为主"的模式下 0 机会是预期行为，但业务上不可用。

### 2.2 多轮采样无增量（搜索覆盖单一）
- **现象**：相同配置连跑 4 轮，50 帖候选 100% 重叠（并集=50）。
- **原因**：查询词固定 → Reddit 搜索结果稳定；posts 截断后每轮同一批。
- **已做的缓解**：subreddit 12→15、查询组 8→14（覆盖 E90/G35/Porsche/Genesis 等新社区），
  但同轮内 posts=50 截断仍是同一批高分帖；posts=200 后单轮覆盖面会显著变大。
- **建议**：若还要多轮累积，需轮换查询词/时间窗口（`--time`），或做跨 run 去重合并。

### 2.3 OpenCLI 数据字段缺失的长期影响
- 评论无真实 id/permalink/created_utc（合成 id `<post_id>-c<index>`，URL 指向帖子页而非评论锚点）→
  证据去重（`duplicate_or_near_duplicate`）和溯源精度受限。
- Task 7 做 stage-hashed checkpoint 时注意：**评论是合成的，同一帖重抓 index 稳定但非真实 id**。
- 若后续需要评论级精确链接，考虑换 rdt-cli / reddit JSON API 通道（项目 README 提到 Agent Reach 可选）。

### 2.4 工作区行尾符噪音（与功能无关）
- worktree 里有 20 个文件 CRLF/LF 噪音改动（忽略行尾后 diff 为空），未提交。
- 处理：`git restore .` 可清掉，不影响内容。

---

## 3. 环境备忘

- **worktree 指针**：`horse-coming-markert-radar-codex-automotive-lighting/.git` 文件当前指向
  WSL 路径（`/mnt/c/...`），**Windows 侧 git.exe 解析不了这个 worktree**（主仓库不受影响）。
  需要切回 Windows 路径时改 `.git` 文件内容即可（`gitdir: C:/Users/25905/...`）。
- **OpenCLI 权限**：Chrome 需保持打开 + Browser Bridge 扩展 + Reddit 登录态；扩展 ID `ildkmabpimmkaediidaifkhjpohdnifk`。
- **已提交**：`03be313`（评论解析/URL/交互）、`e17a9ca`（posts 上限 200）。远程分支已 push 到 cc093d7（Task 6 末）。
- **批处理脚本**：`.local/runs/batch_run_200.sh`（跑到 18:00 自动停，结果在 `batch_results_200.jsonl`）。
- **安全边界不变**：不动 main、不动 v1.1.0、v1.2.0 标签等 Task 8-10 完成验证后再打。

---

## 4. 给 Task 7-10 的建议顺序

1. **Task 7**（checkpoint/失败历史）：注意 OpenCLI 评论合成 id 的稳定性；`--expand-more false` 已是当前适配，checkpoint 复用逻辑已实测可用（同 run-id 续跑跳过已抓详情）。
2. **Task 8**（DSV4Pro 校验回退）：顺带评估 §2.1 质量门——这是当前"报告出不了正式机会"的核心矛盾。
3. **Task 9**（CLI profile + Hermes 交接）：真实运行已证明 OpenCLI 通道可用，overnight 配置可直接复用 `automotive_lighting_us_full.json` 参数。
4. **Task 10**（集成验证 + 发布）：用 200 帖配置跑一轮完整验证；若质量门未调，预期报告会如实显示"样本合格但机会不足/证据不足"，需在 README/交接文档里说明这是规则预期。
