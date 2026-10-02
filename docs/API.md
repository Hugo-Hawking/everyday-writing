<!-- ⓒ 2026 Wu Haoxuan (Hugo-Hawking) · vibe_coding_harness v1.0 · 标识码 VH-2026-08-24 · 使用/修改/分发须获作者授权 -->
# everyday-writing 接口文档（API）

> **适用仓库**：`Hugo-Hawking/everyday-writing`
> **站点**：`https://hugo-hawking.github.io`　**base**：`/everyday-writing/`
> **文章 URL**：`https://hugo-hawking.github.io/everyday-writing/posts/<slug>/`
> **本文档口径**：所有字段、规则、命令均**逐字对照站点仓库源码**（`.github/workflows/{publish,bot-review,deploy}.yml`、`scripts/bot/review_post.py`、`scripts/bot/lib/github_graphql.py`、`src/components/Giscus.astro`、`src/content.config.ts`）写成；源码变更时本文档须同步更新。
> **phase1 实测**：2026-10-02 三条工作流已云端跑通（见文末「附：端到端实测记录」）。

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

**另有两项前置校验**：
- 目标文件 `src/content/posts/<date>_<slug>.md` **已存在 → 报错退出**（不覆盖已有文章）。
- `title`/`description` 写入 frontmatter 时按 YAML double-quoted 标量转义（`\`→`\\`、`"`→`\"`、换行→空格）。

### 1.3 落盘

写入路径：**`src/content/posts/<date>_<slug>.md`**（如 `2026-10-02_my-post.md`）。

frontmatter 字段与 `src/content.config.ts` 的 `posts` schema **严格一致**（5 个字段均必填），顺序固定：

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
5. `addDiscussionComment(discussionId, body=<评论文本>)`。

**已知局限（phase1 简化）**：命中已存在的 Discussion 时**直接追加新评论**，不编辑/去重 → 同一文章重复触发会累积多条 bot 评论。幂等逻辑 phase1 未实现。

### 2.3 权限

```yaml
permissions:
  contents: read     # checkout 读仓库（取变更文章 / 跑脚本）
  discussions: write # bot 建 Discussion + 加评论所需；缺失会**静默 403**
```

### 2.4 事件去重

`concurrency: { group: bot-review-${{ inputs.path || github.event.client_payload.path || github.ref }}, cancel-in-progress: false }`——防同一来源被并发触发时重复建库；但**不能**消除「先后两次触发」的重复评论。

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

## 附：触发与权限汇总

| 接口 | 事件类型 | Workflow | `permissions` | 触发凭据 |
|------|----------|----------|---------------|----------|
| new-post | `repository_dispatch` / `new-post` | `publish.yml` | `contents: write`, `actions: write` | 外部调用方 PAT（`repo` scope） |
| review-post | `repository_dispatch` / `review-post` | `bot-review.yml` | `contents: read`, `discussions: write` | 外部调用方 PAT（`repo` scope） |
| review-post | `workflow_dispatch`（`inputs.path`） | `bot-review.yml` | 同上 | 有 repo 写权限者 / `gh workflow run` |
| review-post | `push`（`src/content/posts/*.md`） | `bot-review.yml` | 同上 | 人工 push / PAT push |
| （部署，非对外接口） | `push`（main） / `workflow_dispatch` | `deploy.yml` | `contents: read`, `pages: write`, `id-token: write` | — |
| read comments | —（只读 GraphQL） | — | —（GraphQL 不接受匿名请求，须带一个有效 token；公开仓库普通 token 即可读，**无需** `discussions: write`） | PAT / `gh auth` |

- 🔴 **`GITHUB_TOKEN` 只能触发 `workflow_dispatch` / `repository_dispatch`**，不能靠 push 链式触发别的 workflow（见 §1.4）。
- 🔴 **外部调用 `repository_dispatch` 必须用带 `repo` scope 的 PAT**，Actions 内的 `GITHUB_TOKEN` 不能向本仓库发 dispatch 以启动另一条工作流。

## 附：端到端实测记录（2026-10-02）

- **new-post 接口冒烟**：一次外部 `gh api -X POST .../dispatches -f event_type=new-post ...`（payload 含 title/slug/date/description/content）触发后，观察到四条 run 全部 success：
  - `Publish Post`（repository_dispatch）→ `Deploy to GitHub Pages`（push）→ `Deploy to GitHub Pages`（workflow_dispatch）+ `Bot Review Post`（workflow_dispatch）。
- **文章上线**：线上文章页 `https://hugo-hawking.github.io/everyday-writing/posts/e2e-smoke-test/` 返回 **HTTP 200**，页面 HTML 含 `data-term="e2e-smoke-test"`。
- **评论落地**：Discussion **#2** 已建——标题 `e2e-smoke-test`、分类 `General`、1 条评论（作者 `github-actions`）。
- **判定标准（plan §1）满足**：打开文章页可见正文 + bot 评论同屏；更早的 `hello-world` 闭环亦经用户**目视确认**评论在页面显示（plan 红队点 1 排除）。
