<!-- ⓒ 2026 Wu Haoxuan (Hugo-Hawking) · vibe_coding_harness v1.0 · 标识码 VH-2026-08-24 · 使用/修改/分发须获作者授权 -->
# everyday-writing 接口文档（API）

> **适用仓库**：`Hugo-Hawking/everyday-writing`
> **站点**：`https://hugo-hawking.github.io`　**base**：`/everyday-writing/`
> **文章 URL**：`https://hugo-hawking.github.io/everyday-writing/posts/<slug>/`
> **本文档口径**：所有字段、规则、命令均**逐字对照站点仓库源码**（`.github/workflows/{publish,bot-review,deploy}.yml`、`scripts/bot/{review_post.py,lib/github_graphql.py,lib/series.py}`、`src/components/Giscus.astro`、`src/content.config.ts`）写成；源码变更时本文档须同步更新。
> **phase1 实测**：2026-10-02 三条工作流已云端跑通（见文末「附：端到端实测记录（2026-10-02）」）。
> **phase2 实测**：2026-10-03 系列小说板块（`series`/`order` 字段 · `/series/` 路由 · 追更记忆）端到端冒烟通过（见文末「附：端到端实测记录（2026-10-03）」）。

---

## 0. 一致性铁律（改任何一处前必读）

🔴 **四处一致性**——下列四处必须是**同一个字符串**（本文档中记作 `<slug>`，如 `hello-world`），否则 giscus 评论区不显示对应 Discussion：

| # | 位置 | 来源 |
|---|------|------|
| 1 | 文章 frontmatter 的 `slug` 字段 | `src/content/posts/<date>_<slug>.md` |
| 2 | 站点 URL 段 `/posts/<slug>/` | `src/pages/posts/[...slug].astro` 的 `getStaticPaths`（`params:{ slug: post.data.slug }`） |
| 3 | giscus 的 `data-term` | `src/components/Giscus.astro`（`data-mapping="specific"` + `data-term={term}`，`term` 由文章页传 `post.data.slug`） |
| 4 | Discussion 标题 | `scripts/bot/review_post.py` 以 `post.slug` 作 `create_discussion(title=...)` |

- **为什么是 `specific` 而非 `pathname`**：`mapping="pathname"` 的 term = `window.location.pathname` 去掉前导 `/`，本站因 base=`/everyday-writing/` 实得 `everyday-writing/posts/<slug>/`（含 base 前缀）——与「标题 = slug」不符。改用 `data-mapping="specific"` 让 term 完全由前端显式给定（= slug），与 base 子目录、末尾斜杠彻底解耦。
- **`data-strict="0"`**：保持默认（按标题搜索）。`strict=1` 并非「标题精确匹配」，而是改用 `sha1(term)` 在 Discussion **body** 里搜——本项目 bot 只写 `title=slug`、不写 sha1，故 `strict=1` 会找不到库。精确性由 bot 侧「搜后校验 `nodes[0].title === slug`」兜住（`scripts/bot/lib/github_graphql.py:find_discussion`）。
- **giscus 固定配置**（`src/components/Giscus.astro`）：`data-repo="Hugo-Hawking/everyday-writing"`、`data-repo-id="R_kgDOU5AWOg"`、`data-category="General"`、`data-category-id="DIC_kwDOU5AWOs4DG48K"`。
  - 分类取 **General**（非 giscus 常荐的 Announcements）：Announcements 限制只有维护者可建帖，而 Discussion 由 Actions 内 `github-actions[bot]`（GITHUB_TOKEN）创建；General 允许任意有权者建帖。

---

## 1. 接口一：new-post（发布文章）

**作用**：一次接口调用 → 在仓库写入文章 md → commit + push → 显式触发部署与评论两条工作流。

**实现**：`.github/workflows/publish.yml`（`name: Publish Post`）。

### 1.1 触发方式

`repository_dispatch`，事件类型 **`new-post`**：

```bash
# gh CLI（推荐）。注意：外部调用方须自带 `repo` scope 的 PAT，
# 不能用 Actions 内的 GITHUB_TOKEN（GITHUB_TOKEN 不能向本仓库发 dispatch 启动另一条工作流）。
gh api -X POST repos/Hugo-Hawking/everyday-writing/dispatches \
  -f event_type=new-post \
  -f client_payload[title]="我的标题" \
  -f client_payload[slug]="my-post" \
  -f client_payload[date]="2026-10-02" \
  -f client_payload[description]="一句话摘要（可省略）" \
  -f client_payload[content]="正文 markdown 内容"
```

等价的 REST 调用：

```http
POST https://api.github.com/repos/Hugo-Hawking/everyday-writing/dispatches
Accept: application/vnd.github+json
Authorization: Bearer <GITHUB_PAT_with_repo_scope>

{ "event_type": "new-post",
  "client_payload": {
    "title": "我的标题", "slug": "my-post", "date": "2026-10-02",
    "description": "一句话摘要", "content": "正文 markdown", "tags": ["随笔"] } }
```

### 1.2 payload 字段

工作流从 `github.event.client_payload` 读取：

| 字段 | 必填 | 规则 | 缺省行为 |
|------|:---:|------|----------|
| `title` | ✔ | 非空；任意字符串 | 无（缺 → `::error::` + 退出 1） |
| `slug` | ✔ | 非空；须匹配 `^[a-z0-9-]+$` | 无（缺 → 报错退出） |
| `date` | ✔ | 非空；须匹配 `^[0-9]{4}-[0-9]{2}-[0-9]{2}$`（`YYYY-MM-DD`） | 无（缺 → 报错退出） |
| `content` | ✔ | 非空；文章正文 markdown | 无（缺 → 报错退出） |
| `description` | ✖ | 任意字符串 | **空则取正文首句**：首个非空行 → 去行首 markdown 标记（`#`/`>`/`*`/`+`/`-`）→ 截到首个句末标点（`。！？.!?`） |
| `tags` | ✖ | 字符串数组 | 缺省 `[]`；若提供则须为字符串数组（`jq` 校验，否则报错退出） |
| `series` | ✖ | 系列 id（phase2）；须匹配 `^[a-z0-9-]+$`，且须对应已存在的 `src/content/series/<series>.md`（否则报错退出，不静默） | 缺省空 → 普通文章；配 `order` 写为系列章节，详见 §1.6 |
| `order` | ✖ | 章节号（phase2）；须匹配 `^[0-9]+$`（非负整数）；**仅当提供 `series` 时可用** | 缺省空；提供 `series` 却缺 `order` → 报错退出 |
| `essay` | ✖ | 随笔标记（phase3）；非空时只接受 `true`/`false`；**与 `series` 互斥**（`essay==true` 且 `series` 非空 → 报错退出） | 缺省空 → 非随笔；`essay=true` 写为随笔，详见 §1.7 |

**另有两项前置校验**：
- 目标文件 `src/content/posts/<date>_<slug>.md` **已存在 → 报错退出**（不覆盖已有文章）。
- `title`/`description` 写入 frontmatter 时按 YAML double-quoted 标量转义（`\`→`\\`、`"`→`\"`、换行→空格）。

### 1.3 落盘

写入路径：**`src/content/posts/<date>_<slug>.md`**（如 `2026-10-02_my-post.md`）。

frontmatter 字段与 `src/content.config.ts` 的 `posts` schema **严格一致**（`title`/`date`/`slug`/`description`/`tags` 五字段均必填；`series`/`order` 为 phase2 新增**可选**字段，见 §1.6；`essay` 为 phase3 新增**可选**字段，见 §1.7），顺序固定：

```markdown
---
title: "<转义后的 title>"
date: <date>
slug: <slug>
description: "<转义后的 description>"
tags: <tags_yaml>
---

<content 正文>
```

- **系列章节**：在 `tags:` 之后、结尾 `---` 之前**追加**两行 `series: <series>` 与 `order: <order>`（二者已由 `Validate payload` 校验为 YAML 安全标量，无需转义）。
- **随笔**（phase3）：在 `tags:` 之后、`series/order` 之前**追加**一行 `essay: true`（仅当 payload `essay == "true"`；已校验为 YAML 安全标量，无需转义）。
- **非系列非随笔文章**（payload 未给 `series`/`essay`）：frontmatter **逐字不变**（不回归 phase1）。

### 1.4 提交与链式触发

工作流以 `github-actions[bot]` 身份 `git commit -m "post: <slug>"` + `git push origin HEAD:main`。

🔴 **关键平台事实**：用仓库自带 `GITHUB_TOKEN` 完成的 push **不会触发其它 workflow**（GitHub 防递归机制；不报错、无 skipped run、Actions 页无任何提示）。因此 `publish.yml` 在 push 之后**显式**调用：

```bash
gh workflow run deploy.yml   --repo Hugo-Hawking/everyday-writing --ref main
gh workflow run bot-review.yml --repo Hugo-Hawking/everyday-writing --ref main -f path=<POST_PATH>
```

- 依据：`workflow_dispatch` / `repository_dispatch` 是上述防递归规则的**两个例外**（GitHub 自 2022-09-08 起放行）。
- 编译要求：本 workflow 声明 `permissions: { contents: write, actions: write }`（`actions: write` 是 `gh workflow run` 端点所需）。

### 1.5 权限

```yaml
permissions:
  contents: write   # 写文章 md 并 git push
  actions: write    # gh workflow run 显式触发 deploy.yml / bot-review.yml
```

### 1.6 系列章节：可选 `series`/`order`（phase2）

`new-post` payload 新增两个**可选**字段，用于发布连载小说的章节（字段语义与路由详见 §4）：

| 字段 | 规则 | 校验失败行为 |
|------|------|--------------|
| `series` | 系列 id；须匹配 `^[a-z0-9-]+$`；须对应已存在的 `src/content/series/<series>.md` | `::error::` + 退出 1（不静默） |
| `order` | 章节号（字符串形式整数）；须匹配 `^[0-9]+$`；**提供 `series` 时必填** | `::error::` + 退出 1 |

四条**联动校验规则**（`Validate payload` 步骤，`publish.yml`）：

1. `series` 非空 → 须匹配 `^[a-z0-9-]+$`；
2. `series` 非空 → `order` 须非空，且匹配 `^[0-9]+$`；
3. `series` 非空 → `src/content/series/<series>.md` 须已存在，否则报错退出（指向不存在的系列元数据）；
4. `series` 为空而 `order` 非空 → 报错退出（`order` 仅用于系列章节）。

二者**均缺省** → 按普通文章处理，不写这两行（phase1 行为不变）。

**带系列字段的 payload 示例**（把 `demo-novel` 系列第 2 章发上去）：

```bash
gh api -X POST repos/Hugo-Hawking/everyday-writing/dispatches \
  -f event_type=new-post \
  -f client_payload[title]="第二章 归途" \
  -f client_payload[slug]="demo-novel-ch2" \
  -f client_payload[date]="2026-10-03" \
  -f client_payload[description]="第二章的一句话摘要" \
  -f client_payload[series]="demo-novel" \
  -f client_payload[order]="2" \
  -f client_payload[content]="第二章正文 markdown 内容"
```

> 前置条件：`src/content/series/demo-novel.md`（系列元数据）须已存在于仓库，否则本调用因规则 3 被拒。

### 1.7 随笔：可选 `essay`（phase3）

`new-post` payload 新增一个**可选**字段，用于发布**日常随笔**（字段语义与路由详见 §4.6）：

| 字段 | 规则 | 校验失败行为 |
|------|------|--------------|
| `essay` | 非空时须为 `true` 或 `false`（字符串形式）；`essay == "true"` 时 `series` 须为空（**互斥**） | `::error::` + 退出 1（不静默） |

- **缺省**（或 `essay: false`）→ 非随笔，frontmatter 不写该行（phase1/2 行为不变）。

**带 essay 的 payload 示例**（发布一篇随笔）：

```bash
gh api -X POST repos/Hugo-Hawking/everyday-writing/dispatches \
  -f event_type=new-post \
  -f client_payload[title]="雨天的咖啡馆" \
  -f client_payload[slug]="essay-rain" \
  -f client_payload[date]="2026-10-03" \
  -f client_payload[content]="随笔正文 markdown 内容" \
  -f client_payload[essay]="true"
```

---

## 2. 接口二：review-post（触发/重触发评论）

**作用**：对指定文章跑 AI bot（DeepSeek）生成评论，写入该文对应的 Discussion。

**实现**：`.github/workflows/bot-review.yml`（`name: Bot Review Post`）→ 调用 `scripts/bot/review_post.py --path <file> --commit`。

### 2.1 三种触发方式与目标解析

| 触发方式 | 事件 | 目标文章来源 | 说明 |
|----------|------|-------------|------|
| **文章内容变更** | `push`（`paths: ['src/content/posts/*.md']`） | `git diff --name-only --diff-filter=ACMR HEAD^ HEAD -- 'src/content/posts/*.md'` | 取本次 push 最后一个提交里新增/复制/修改/重命名的文章（排除删除） |
| **手动** | `workflow_dispatch` | `inputs.path` | 参数 `path`（相对仓库根），必填，默认 `src/content/posts/2026-10-02_hello-world.md` |
| **接口层** | `repository_dispatch`（事件类型 **`review-post`**） | `client_payload.path` | payload 须含 `path` 字段 |

任一触发的目标为空/解析不到 → `::error::` + 退出 1（**不静默放行**）。`push` 触发在无父提交（首次推送/浅克隆）时同样报错退出。

> **例外（2026-10-02 修订）：`push` 纯删除文章**。`push` 分支用 `--diff-filter=ACMR` 排除删除；若本次 push 只删文（解析到 0 篇），则输出 `::notice::` 并以 0 退出（**绿 run**），同时以 `has_targets=false` 让 `Run bot` 步骤**跳过**（不评论）——「本无事可做」不再表达为失败。其余空结果（`workflow_dispatch`/`repository_dispatch` 缺 `path`、未知事件、`push` 无父提交）仍一律 `::error::` + 退出 1。

**repository_dispatch 调用样例**：

```bash
gh api -X POST repos/Hugo-Hawking/everyday-writing/dispatches \
  -f event_type=review-post \
  -f client_payload[path]="src/content/posts/2026-10-02_hello-world.md"
```

**workflow_dispatch 调用样例**：

```bash
gh workflow run bot-review.yml --repo Hugo-Hawking/everyday-writing --ref main \
  -f path="src/content/posts/2026-10-02_hello-world.md"
```

### 2.2 行为

对每个目标 md 运行：

```
python scripts/bot/review_post.py --path <file> --commit
```

流程（`scripts/bot/review_post.py`）：
1. 解析 md → `frontmatter` + 正文 + `slug`（缺 `slug`/`title` 报错退出）。
2. 组 prompt（system 角色设定 + user 文章标题与正文）→ 调 DeepSeek `deepseek-chat` → 得评论文本。
3. `find_discussion(token, REPO, slug, CATEGORY_ID)`：`search(type:DISCUSSION, last:1, query:"repo:hugo-hawking/everyday-writing in:title \"<slug>\"")`，命中条件 = `nodes[0].title === slug` **且** `nodes[0].category.id === CATEGORY_ID`。
4. 未命中 → `createDiscussion(repositoryId, categoryId, title=<slug>, body=<占位正文>)`，标题 = slug。
5. **评论落库（phase4 起改为「先增后删、收敛为一条」）**：`listDiscussionComments(discussionId)` 列出该 Discussion 顶层评论 → `pick_bot_comments` 仅按 `author.login` 挑出 bot 自己的评论（纯过滤，不排序）：
   - **先** `addDiscussionComment(discussionId, body=<评论文本>)` **新增**一条最新评论；
   - **再** 对每条更旧的 bot 评论（`id != 新评论 id`）`deleteDiscussionComment` **删除** → 收敛为恰一条（内容为最新）。
   - 🔴 **不用 `updateDiscussionComment` 原地更新**：Actions 的 App 身份（`GITHUB_TOKEN`）调用恒 `FORBIDDEN: Resource not accessible by integration` → 故以「增删替换」实现「同一文章至多一条 bot 评论」。
   - 详见 §2.5。

### 2.3 权限

```yaml
permissions:
  contents: write    # phase2：bot 提交追更记忆文件 data/series/<id>.md 所需（原为 read，见 §4.5）
  discussions: write # bot 建 Discussion + 加评论所需；缺失会**静默 403**
```

### 2.4 事件去重

`concurrency: { group: bot-review, cancel-in-progress: false }`——防同一来源被并发触发时重复建库；但**不能**消除「先后两次触发」的重复评论。

> **phase2 变更**：`group` 由「按文章路径」改为**全局 `bot-review`**——同系列不同章并发会争同一记忆文件（`data/series/<id>.md`），全局串行消除该竞态（代价：不同文章不再并行）。详见 §4.5。

### 2.5 bot 评论策略（phase4 · 同一文章至多一条 bot 评论）

同一篇文章的 Discussion **至多保留一条 bot 评论**；bot 重推（同文再次触发 review-post）时**先新增最新评论、再删除旧 bot 评论**（替换而非追加），避免旧评论堆积、最新评价被顶上。

| 情形 | 行为 |
|------|------|
| Discussion 不存在 | 新建 Discussion（标题 = slug，占位正文），随后走下方「无 bot 评论」路径 |
| Discussion 存在、**无** bot 评论 | `addDiscussionComment` **新增**一条 bot 评论 |
| Discussion 存在、**有** bot 评论 | **先** `addDiscussionComment` 新增最新评论 → **再** `deleteDiscussionComment` 删除更旧的 bot 评论 → bot 评论恰一条、内容为最新（新 id） |

- 🔴 **为何用「替换」而非「原地更新」**：Actions 的 App 身份（`GITHUB_TOKEN`）调用 `updateDiscussionComment` **恒返回 `FORBIDDEN: Resource not accessible by integration`**（对既有评论与本轮刚建的评论均如此，2026-10-03 云端实测）→ 平台不允许 App 编辑评论，故以「先增后删」实现「至多一条」。**代价**：重推后评论 **node id 会变**（permalink/锚点变化、reactions 归零）；本项目 giscus 全量渲染评论正文、无依赖固定锚点，可接受。
- **识别 bot 评论**：仅按 `author.login == BOT_COMMENT_AUTHOR`（默认 `github-actions`，可用同名环境变量覆盖）。🔴 **不得用 `viewerDidAuthor`**——以 OAuth 身份查询 bot 评论时该字段恒为 `false`（2026-10-03 实测，见 plan §4 假设 4）。
- 🔴 **人类读者评论不受影响**：过滤条件严格 `login == BOT_COMMENT_AUTHOR`；删除额外排除刚新增的 `new_id`。人类评论永不被选中、永不被删。
- **顺序铁律：先新增、后删除**——`_graphql` 无重试。先增后删时，新增失败即 `FATAL` 退出（旧评论仍在，评论不丢）；删除失败最坏暂留 2 条（下轮自愈）。**禁止**先删后增（新增失败将导致 0 条、评论丢失）。
- **无 `orderBy`**：`Discussion.comments` 不接受 `orderBy` 参数 → 但本方案删「所有更旧的 bot 评论」，与顺序无关，故 `pick_bot_comments` 只过滤、不排序。
- **系列追更记忆不变**：`data/series/<id>.md` 的二次调用与落盘逻辑（§4.4/§4.5）**不受本策略影响**；本策略只改「评论文本如何落到 Discussion」。
- **不回归**：dry-run / `--show-context` 路径不触网（不调 list/add/delete）；随笔、非系列文章照旧走普通读后感路径。

---

## 3. 接口三：read comments（读取某篇文章的评论）

**评论载体**：GitHub Discussions。**每篇文章对应一个 Discussion，标题 = 文章 slug**。

**读取方式**：按 Discussion 标题（= slug）查 GraphQL。前端（giscus）在页面里也是按 `data-term`（= slug，`mapping=specific`）匹配同一个 Discussion 并把评论渲染出来——所以「页面看到的评论」与「接口读到的评论」是同一份数据。

### 3.1 GraphQL 查询样例（一条 query 直接拿标题匹配 + 评论）

```bash
gh api graphql -f query='
query($q: String!) {
  search(type: DISCUSSION, last: 1, query: $q) {
    discussionCount
    nodes {
      ... on Discussion {
        id
        number
        title
        url
        comments(first: 50) {
          nodes {
            author { login }
            body
            createdAt
            url
          }
        }
      }
    }
  }
}' -f q='repo:hugo-hawking/everyday-writing in:title "hello-world"'
```

- `$q` 形如 `repo:hugo-hawking/everyday-writing in:title "<slug>"`（repo 必须**小写**）。
- `search` 的标题匹配是 GitHub **模糊搜索**（token 化、非精确相等）→ 调用方**须自行校验** `nodes[0].title === "<slug>"`（与 bot 侧 `find_discussion` 同一容错口径）。
- 若已知 Discussion 序号 `number`，也可直取（等价、无需搜索）：

```bash
gh api graphql -f query='
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    discussion(number: $number) {
      title
      comments(first: 50) { nodes { author { login } body createdAt } }
    }
  }
}' -f owner=Hugo-Hawking -f name=everyday-writing -F number=2
```

### 3.2 返回字段样例

`search.nodes[0]`（`... on Discussion` 投影）：

```json
{
  "id": "D_kwDOU5AWOg4A...",
  "number": 2,
  "title": "e2e-smoke-test",
  "url": "https://github.com/Hugo-Hawking/everyday-writing/discussions/2",
  "comments": {
    "nodes": [
      { "author": { "login": "github-actions" },
        "body": "> 🤖 DeepSeek 自动评论\n\n## 读后感想\n...",
        "createdAt": "2026-10-02T...Z",
        "url": "https://github.com/Hugo-Hawking/everyday-writing/discussions/2#discussioncomment-..." }
    ]
  }
}
```

- `comments.nodes[].body` = 评论正文（markdown；bot 评论文本格式见 `review_post.py:SYSTEM_PROMPT`）。
- **注意**：Discussion 的**首帖正文**（`createDiscussion` 的 `body`）是占位文字（`review_post.py:DISCUSSION_PLACEHOLDER_BODY`），**不是**评论；AI 评论以 DiscussionComment 形式追加在 `comments` 下，作者为 `github-actions`。

### 3.3 前端匹配（giscus）

`src/components/Giscus.astro` 以 `data-mapping="specific"` + `data-term={slug}` 让 giscus 用 slug 作 term 查找 Discussion（标题匹配）。因此：**只要 Discussion 标题 = slug，页面评论区即显示该 Discussion 的评论**。

---

## 4. 系列小说：内容字段、路由与追更记忆（phase2）

> 本节对应 plan `2026-10-03_phase2_系列小说板块` 步骤 1–8；实现落在站点仓库 `src/content.config.ts`、`src/pages/{series/*,posts/[...slug]}.astro`、`scripts/bot/{review_post.py,lib/series.py}`、`.github/workflows/{publish,bot-review}.yml`。

### 4.1 内容字段（`posts` frontmatter 扩展）

`posts` 集合新增两个**可选**字段（`src/content.config.ts`）：

| 字段 | 类型 | 必填 | 说明 |
|------|------|:---:|------|
| `series` | `string` | ✖ | 引用 `src/content/series/<id>.md` 的系列 id（= 文件名去扩展名） |
| `order` | `number` | ✖ | 章节号；**有 `series` 时必填**（由 `publish.yml` / bot 侧校验，schema 不强绑） |

- 🔴 **必须 optional**：现文 `2026-10-02_hello-world.md` 无此二字段；若设为必填，`astro build` 会直接失败（红队点 R1 已复现：设必填 → `InvalidContentEntryDataError`，改回 optional → 构建通过）。
- **系列元数据集合** `series`（`src/content/series/*.md`）：schema `title`（必填）、`description?`、`status`（`'连载中'` / `'完结'`，默认 `'连载中'`）、`cover?`；条目 id = 文件名去扩展名（= `posts.series` 的取值域）。

### 4.2 路由与页面

| 路由 | 页面 | 内容 |
|------|------|------|
| `/series/` | `src/pages/series/index.astro` | **系列总览**：列出所有系列（书名 / 简介 / 状态 / 章节数），链到 `/series/<系列 id>/` |
| `/series/<系列 id>/` | `src/pages/series/[slug].astro` | **目录页**：该系列全部章节，按 `order` **升序**排列，每章可点入 |
| `/posts/<slug>/` | `src/pages/posts/[...slug].astro` | **章节页**（URL 形态**不变**）；系列章节额外渲染「← 上一章 / 目录 / 下一章 →」导航（同系列按 `order` 取前后章）；非系列文章**不渲染**该导航 |

- 🔴 **四处一致性在新路由下不变**（见 §0）：`frontmatter slug` ＝ `/posts/<slug>/` ＝ giscus `data-term` ＝ Discussion 标题。giscus `data-term` 仍取自 `post.data.slug`，与 `/series/` 路由无关（系列页不挂 giscus）。
- 站内链接一律带 `import.meta.env.BASE_URL`（base = `/everyday-writing/`）。

### 4.3 追更记忆文件 `data/series/<系列 id>.md`

- **由 bot 维护**（`scripts/bot/review_post.py` + `scripts/bot/lib/series.py`）；文件位于 `src/` 之外，**Astro 不构建它**、也不匹配 `bot-review.yml` 的 `paths`（写它不触发自评）。
- **格式（phase5 起）**：头部说明 + **`## 全书脉络`（canon）段** + 逐章条目（`## 第 N 章 <标题> (slug: <slug>)`，其下 `- 梗概：…` / `- 人物/伏笔：…`，后者可省）。

```markdown
# 追更记忆：<系列标题>

> 本文件由 bot 维护，记录已读章节的梗概与线索；请勿手工改（会被下次评论覆盖）。

## 全书脉络
（长期摘要：主要人物、核心设定、未回收伏笔。每章由记忆调用**整体重写**，目标 ≤ 800 字；
 吸收滚出窗口的旧条目的要点。）

## 第 <N> 章 <章标题> (slug: <slug>)
- 梗概：…
- 人物/伏笔：…
```

- **`## 全书脉络`（canon）**：由**记忆调用每章滚动重写**——把上一版 canon、最近条目与当前章合并成一份长期摘要。它承担「超出窗口的早期章节要点」，因此**更早的章节不再逐条保留**。
- **逐章条目只保留最近 M 条**（M 默认 12）：纳入 prompt 与落盘时都封顶；被逐出的更早条目的要点**靠 canon 承载**（**取舍代价**：长线细节由模型自压缩，可能不完美，不再逐字保留中段情节）。
- 🔴 **canon 守卫滚动**：`update_memory` **仅当本轮 canon 非空**才丢弃超出 M 的旧条目；canon 为空（记忆调用未产出该块）时**条目全留**——宁可文件变长，不因 canon 写失败而丢记忆。
- **向后兼容**：既有记忆文件**无 canon 段**时按「canon 为空」处理（`parse_canon` 返回 `""`，上下文以占位符顶替）；下次 `--commit` 会自动补写 canon 段。

### 4.3.1 三个可配置项

| 配置项 | 环境变量 | 默认值 | 语义 |
|--------|----------|:---:|------|
| 纳入记忆条数上限 | `SERIES_MEMORY_K` | `12` | 纳入 prompt 与落盘的**记忆条目数**上限（超出**从最早丢**） |
| 纳入记忆字符上限 | `SERIES_MEMORY_CHAR_LIMIT` | `12000` | 纳入 prompt 的**记忆条目总字符**上限（超出从最早丢，**至少留 1 条**） |
| prompt 字符预算 | `DEEPSEEK_PROMPT_CHAR_BUDGET` | `60000` | 单次 DeepSeek 调用 prompt 字符总量上限；**超出即快速失败**（见 §4.4） |

- 章节原文侧另有 `SERIES_CONTEXT_K`（默认 10）/`SERIES_CONTEXT_CHAR_LIMIT`（默认 16000），与本表**相互独立**（见 §4.4）。

### 4.3.2 prompt 预算护栏（超预算硬失败）

- 每次 DeepSeek 调用前，bot 以 `sum(len(msg["content"]))` 估算 prompt 字符总量（评论调用、记忆调用**各一次**，二者 user 消息同源）。
- 超过 `DEEPSEEK_PROMPT_CHAR_BUDGET`（默认 60000）→ **立即快速失败**（`FATAL`，打印 `label`、估算字符与上限、提示可调该环境变量），**不发**这次付费请求。
- 🔴 **不做自动裁剪、不静默降级**：超预算即停（宁可该章无评论，也不发注定失败的调用、不悄悄丢上下文）。该章可调大预算或缩短正文后重推。

### 4.4 bot 追更行为（系列章）

对 `frontmatter.series` 非空的章节，`review_post.py` 走**追更路径**（非系列文章走原路径，**不回归** phase1）：

1. **两次 DeepSeek 调用**：第一次生成**评论**（发 Discussion，契约与普通文章一致——`> 🤖 DeepSeek 自动评论` + 三段结构）；第二次生成**记忆两块**——`【全书脉络】`（canon，整体重写）+ `【本章条目】`（当前章 `- 梗概 / - 人物·伏笔`），供落盘。第二次调用**先于**「发评论」执行——若失败则快速中止，避免「评论已发但记忆未写」的半完成态。
2. **每次调用前过 prompt 预算护栏**（§4.3.2）：估算 prompt 字符总量，超 `DEEPSEEK_PROMPT_CHAR_BUDGET` 即**快速失败**（`FATAL`）、**不发请求**；评论调用与记忆调用**各守卫一次**（二者 user 同源，一起挡）。
3. **追更上下文** = **全书脉络（canon）** + 前情记忆（记忆文件中 `order < 当前` 的条目，**双上限**：至多 `SERIES_MEMORY_K` 条且条目总字符 ≤ `SERIES_MEMORY_CHAR_LIMIT`，从最早丢、至少留 1 条）+ 同系列**最近 K 章**原文（默认 **K = 10**，环境变量 `SERIES_CONTEXT_K` 覆盖；前序原文总字符上限默认 **16000**，`SERIES_CONTEXT_CHAR_LIMIT` 覆盖，超限时**从更早的章丢弃**，至少保留最近 1 章）。三段相互独立。
4. **幂等 + 滚动**：记忆条目按 `order` / `slug` 去重，重评同章**替换**而不重复；落盘按 `order` 升序；**仅当本轮 canon 非空**才把超出 M 的旧条目滚动丢弃（见 §4.3），并写出本轮 canon 段。
5. **`--commit` 守卫**：第二次调用产出**记忆条目为空或 canon 为空** → 快速失败（不写坏记忆、不发评论）。
6. **写盘时机**：`--commit` 才写评论 + 记忆文件；dry-run 与 `--show-context` **均不写**。

### 4.5 记忆文件的提交

记忆文件的 git 提交由 `bot-review.yml` 的 **`Commit series memory`** 步骤完成（排在 `Run bot` 之后）：

- `permissions` 由 `contents: read` 提升为 **`contents: write`**（bot 提交记忆所需）。
- **只 `git add data/series/`**（禁用 `git add -A` / `.`，缩小写权限的 blast radius）；无暂存变化则跳过（不产空 commit）。
- push 前 **`git pull --rebase origin main`** + 失败重试 ≤ 3 次（防非快进）。
- 该 push 用 `GITHUB_TOKEN` → **不触发任何其它 workflow**（GitHub 防递归，见 §1.4）。
- `concurrency.group` 由「按文章路径」改为**全局 `bot-review`**：同系列不同章并发会争同一记忆文件，全局串行消除该竞态（代价：不同文章不再并行）。

### 4.6 随笔：内容字段、路由与「无追更」（phase3）

> 本节对应 plan `2026-10-03_phase3_随笔板块` 步骤 1–5；实现落在站点仓库 `src/content.config.ts`、`src/pages/essays/index.astro`、`src/layouts/Base.astro`、`.github/workflows/publish.yml`。

- **内容字段**：`posts` 集合新增可选布尔 `essay`（`src/content.config.ts`）。`essay: true` ⇔ 随笔（省略或 `false` = 非随笔）。
  - 🔴 **必须 optional**：现文 `2026-10-02_hello-world.md` 无此字段；若设为必填，`astro build` 直接失败。
- **路由**：

  | 路由 | 页面 | 内容 |
  |------|------|------|
  | `/essays/` | `src/pages/essays/index.astro` | **随笔专列页**：按 `date` **倒序**列出全部 `essay: true` 的文章（同日以 `slug` 升序作稳定次级键），每项 = 标题 + 日期，链到 `/posts/<slug>/`；**无**「第 N 章」等序号字样 |
  | `/posts/<slug>/` | `src/pages/posts/[...slug].astro` | **复用文章页**（URL 形态**不变**；随笔**不**新开 `/essays/<slug>/`）→ 四处一致性不变（§0），评论区正常 |

- **首页**：`/everyday-writing/` **照旧列出全部文章（含随笔）**——`/essays/` 只是专列页，**不取代**首页（用户 2026-10-03 拍板，随笔不隐藏）。
- **与系列的区别（无追更）**：随笔**无追更记忆**（不写 `data/series/**`）；随笔**不触发** bot 追更路径——bot **不读取** `essay` 字段，识别只靠「无 `series`」（`scripts/bot/review_post.py` 的 `if post.frontmatter.get("series"):` 分支）→ 走**普通读后感**路径（评论文结构与普通文章一致）。
- **导航**：`src/layouts/Base.astro` 顶部新增全站导航：首页 / 系列 / 随笔。

---

## 附：触发与权限汇总

| 接口 | 事件类型 | Workflow | `permissions` | 触发凭据 |
|------|----------|----------|---------------|----------|
| new-post | `repository_dispatch` / `new-post` | `publish.yml` | `contents: write`, `actions: write` | 外部调用方 PAT（`repo` scope） |
| review-post | `repository_dispatch` / `review-post` | `bot-review.yml` | `contents: write`, `discussions: write` | 外部调用方 PAT（`repo` scope） |
| review-post | `workflow_dispatch`（`inputs.path`） | `bot-review.yml` | 同上 | 有 repo 写权限者 / `gh workflow run` |
| review-post | `push`（`src/content/posts/*.md`） | `bot-review.yml` | 同上 | 人工 push / PAT push |
| （部署，非对外接口） | `push`（main） / `workflow_dispatch` | `deploy.yml` | `contents: read`, `pages: write`, `id-token: write` | — |
| read comments | —（只读 GraphQL） | — | —（GraphQL 不接受匿名请求，须带一个有效 token；公开仓库普通 token 即可读，**无需** `discussions: write`） | PAT / `gh auth` |

- 🔴 **`GITHUB_TOKEN` 只能触发 `workflow_dispatch` / `repository_dispatch`**，不能靠 push 链式触发别的 workflow（见 §1.4）。
- 🔴 **外部调用 `repository_dispatch` 必须用带 `repo` scope 的 PAT**，Actions 内的 `GITHUB_TOKEN` 不能向本仓库发 dispatch 以启动另一条工作流。
- **phase2 变更**：`bot-review.yml` 的 permissions 由 `contents: read` 提升为 **`contents: write`**——追更记忆文件（`data/series/<id>.md`）的提交需仓库写权限（见 §4.5）。

## 附：端到端实测记录（2026-10-02）

- **new-post 接口冒烟**：一次外部 `gh api -X POST .../dispatches -f event_type=new-post ...`（payload 含 title/slug/date/description/content）触发后，观察到四条 run 全部 success：
  - `Publish Post`（repository_dispatch）→ `Deploy to GitHub Pages`（push）→ `Deploy to GitHub Pages`（workflow_dispatch）+ `Bot Review Post`（workflow_dispatch）。
- **文章上线**：线上文章页 `https://hugo-hawking.github.io/everyday-writing/posts/e2e-smoke-test/` 返回 **HTTP 200**，页面 HTML 含 `data-term="e2e-smoke-test"`。
- **评论落地**：Discussion **#2** 已建——标题 `e2e-smoke-test`、分类 `General`、1 条评论（作者 `github-actions`）。
- **判定标准（plan §1）满足**：打开文章页可见正文 + bot 评论同屏；更早的 `hello-world` 闭环亦经用户**目视确认**评论在页面显示（plan 红队点 1 排除）。

## 附：端到端实测记录（2026-10-03 · 系列小说板块）

- **场景**：push 一部 3 章的 demo 系列（`demo-novel`：ch1 / ch2 / ch3）。
- **Bot Review**：run `37110907914` 绿（约 30s）——为 3 章各建 Discussion（**#5 / #4 / #3**）并写入追更评论；`Commit series memory` 步骤第 1 次 `pull --rebase` + push **成功**，远端提交 `8a771b2` **仅改动 `data/series/demo-novel.md`**（提交面限制生效，§4.5）。
- **Deploy**：run `37110907878` 绿（约 34s）；线上 `/series/`、`/series/demo-novel/`、`/posts/demo-novel-ch2/` 均返回 **HTTP 200**。
- **防递归**：记忆文件的 push **未触发**任何新的 workflow run（`GITHUB_TOKEN` push 不触发，§1.4 假设成立）。
- **路由与排序**：目录页章节顺序 ch1 → ch2 → ch3（按 `order` 升序，而三章的文件/日期顺序为反序，故排序确非按路径/日期）；章节页「上一章 / 目录 / 下一章」导航与 giscus `data-term`（= 章节 slug）均正确。
