"""追更上下文：读写记忆文件 + 扫同系列前序章节 + 组装追更 prompt 上下文。仅标准库。

记忆文件约定（code_structure §6）：`data/series/<系列 id>.md`
    —— `<系列 id>` = `src/content/series/<id>.md` 文件名；
    每章一条 `## 第 <order> 章 <标题> (slug: <slug>)`，其下 `- 梗概：…` / `- 人物/伏笔：…`。
`data/` 在 `src/` 之外：Astro 不构建它、也不匹配 bot-review 的 `paths`（不触发自评）。

ref: reference/plans/2026-10-03_phase2_系列小说板块/plan.md §3 步骤 5
ref: reference/plans/2026-10-03_phase2_系列小说板块/code_structure.md §4/§6
"""

import os
import re

from lib.md_parse import parse_post        # ref: code_structure §1（scripts/bot/lib/md_parse.py，复用解析）

# 默认纳入的「最近 K 章」原文（plan §3 步骤5：默认 K=10，可配置）
DEFAULT_K = 10
# 前序章节原文块的总字符上限（红队点 R4：防「记忆 + K 章 + 当前章」超上下文窗口）
DEFAULT_CHAR_LIMIT = 16000

# 纳入 prompt 的「记忆条目」条数上限（phase5 plan §3 步骤1；env: SERIES_MEMORY_K）
DEFAULT_MEMORY_K = 12
# 纳入 prompt 的「记忆条目」总字符上限（phase5 plan §3 步骤1；env: SERIES_MEMORY_CHAR_LIMIT）
DEFAULT_MEMORY_CHAR_LIMIT = 12000
# 记忆文件 canon（全书脉络）段标题（phase5 plan §3 步骤1）
CANON_HEADING = "## 全书脉络"

# 记忆文件头部（新建文件时用；已有文件则保留其原头部）
# ref: code_structure §6（记忆文件格式）
_MEMORY_HEADER = (
    "# 追更记忆：%s\n"
    "\n"
    "> 本文件由 bot 维护，记录已读章节的梗概与线索；请勿手工改（会被下次评论覆盖）。\n"
)

# 记忆条目标题行：`## 第 <order> 章 <title> (slug: <slug>)`
_ENTRY_HEAD_RE = re.compile(r"^##\s*第\s*(\d+)\s*章\s*(.*?)\s*\(slug:\s*([^)]+)\)\s*$")


def resolve_repo_root(post_path):
    """由 --path 推导仓库根：路径须位于 `<root>/src/content/posts/` 下。

    Actions cwd=仓库根、本地 cwd 可能不同（plan §3 步骤5 注）；两种环境都按
    「posts 目录上溯三级」定位，使 `data/series/<id>.md` 与 `src/content/posts/` 的扫描
    在两种环境下一致。

    ref: plan §3 步骤5 关键坑（由 --path 推导仓库根）
    """
    posts_dir = os.path.dirname(os.path.abspath(post_path))                  # ref: 由 --path 取 posts 目录
    if not posts_dir.replace(os.sep, "/").endswith("src/content/posts"):
        raise ValueError("无法从 --path 推导仓库根（期望路径含 src/content/posts/）：%s" % post_path)
    return os.path.dirname(os.path.dirname(os.path.dirname(posts_dir)))      # ref: posts→content→src→root


def memory_path(repo_root, series_id):
    """记忆文件路径 = `<repo_root>/data/series/<系列 id>.md`。

    ref: plan §3 步骤4（data/ 在 src/ 外，Astro 不构建、不触发 bot-review）
    """
    return os.path.join(repo_root, "data", "series", series_id + ".md")


def load_memory(repo_root, series_id):
    """读记忆文件；不存在 → 返回 ""（合法初始态，非错误）。

    ref: 站点知识 §7.5（首次 bootstrap：文件不存在 = 空记忆）
    ref: RULES §12.3（文件不存在是系统边界的合法初始态）
    """
    path = memory_path(repo_root, series_id)
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as fh:                          # ref: 系统边界：读文件
        return fh.read()


def parse_memory_entries(memory_text):
    """解析记忆文件为条目列表 `[{order:int, title, slug, block}]`（block 无尾换行）。

    ref: code_structure §6（记忆文件格式）
    """
    entries = []
    cur = None
    for line in memory_text.split("\n"):
        m = _ENTRY_HEAD_RE.match(line)
        if m:
            if cur is not None:
                entries.append(cur)
            cur = {"order": int(m.group(1)), "title": m.group(2), "slug": m.group(3), "block": line}
            continue
        if cur is not None:                                                # ref: 归入当前条目
            cur["block"] += "\n" + line
    if cur is not None:
        entries.append(cur)
    for e in entries:
        e["block"] = e["block"].rstrip("\n")                               # ref: 规整：去块尾空行
    return entries


def parse_canon(memory_text):
    """取 `## 全书脉络` 段正文（到下一个 `## ` 标题前）；无该段 → 返回 ""。

    ref: plan §3 步骤1；plan §4 假设5（现文件无 canon 段按空处理）
    ref: code_structure §2.1（解析实现）
    """
    lines = memory_text.split("\n")
    out, in_canon = [], False
    for ln in lines:
        if ln.strip().startswith(CANON_HEADING):                          # ref: 命中 canon 标题行 → 进入
            in_canon = True
            continue
        if in_canon and re.match(r"^##\s", ln):                           # ref: 下一个二级标题（含 `## 第 N 章`）→ canon 结束
            break
        if in_canon:
            out.append(ln)
    return "\n".join(out).strip()


def _order_of(frontmatter, path):
    """取系列章节的整数 order。md_parse 不做类型转换（返回 str）→ 此处 `int()` 并显式容错。

    ref: 站点知识 §5.2（md_parse 无类型转换，order 为字符串 "1"）
    ref: plan §3 步骤5 关键坑（缺 order / 非法值 → 明确报错，不静默）
    """
    raw = frontmatter.get("order")
    if raw is None or raw == "":
        raise ValueError("系列章节缺少必填字段 'order'：%s" % path)
    try:
        return int(str(raw).strip())
    except ValueError:
        raise ValueError("系列章节 'order' 非整数：%r（%s）" % (raw, path))


def scan_prior_chapters(repo_root, series_id, current_order):
    """扫 `src/content/posts/*.md` 中 `series==<id>` 且 `order<当前` 的章节。

    返回按 order **降序**（最近在前）的 `[{order, title, slug, body, path}]`。

    ref: plan §3 步骤5（扫同系列 order 小于当前的章节）
    """
    posts_dir = os.path.join(repo_root, "src", "content", "posts")
    found = []
    for name in sorted(os.listdir(posts_dir)):
        if not name.endswith(".md"):
            continue
        path = os.path.join(posts_dir, name)
        post = parse_post(path)                                            # ref: code_structure §1（复用 md_parse）
        fm = post.frontmatter
        if fm.get("series") != series_id:                                  # ref: 只取同系列章节
            continue
        order = _order_of(fm, path)                                        # ref: 显式 int + 容错
        if order < current_order:
            found.append({"order": order, "title": fm.get("title", ""), "slug": post.slug,
                          "body": post.body, "path": path})
    found.sort(key=lambda c: c["order"], reverse=True)                     # ref: 最近 K 章 → order 降序
    return found


def _total_len(chapters):
    """前序章节原文的总字符数（长度截断判据）。"""
    return sum(len(c["body"]) for c in chapters)


def build_context(memory_entries, canon, prior_chapters, current_order, k, char_limit,
                  memory_k, memory_char_limit):
    """组装追更上下文：全书脉络（canon） + 前情记忆（order<当前，双上限） + 最近 K 章原文（含长度截断）。

    返回 `(context_str, stats)`；stats 增 `memory_dropped`/`memory_chars`/`canon_len`。
    记忆只取 `order < 当前`（前情），避免泄漏「未来」章节。
    记忆块双上限：先按**条数**（`len > memory_k` 丢最早）、再按**字符**（从最早丢，至少留 1 条）。

    ref: plan §3 步骤1（记忆块双上限 + canon 前缀）；plan §8 R2（canon 超长由调用方护栏兜底）
    ref: plan §8 红队点 R4（章节原文超长 → 从更早的章丢弃）
    """
    used_memory = [e for e in memory_entries if e["order"] < current_order]    # ref: 前情=order<当前
    memory_dropped = 0
    while len(used_memory) > memory_k:                                       # ref: 条数上限：丢最早（列表按 order 升序）
        used_memory.pop(0)
        memory_dropped += 1
    while (len(used_memory) > 1                                              # ref: 字符上限：从最早丢，至少留 1 条
           and sum(len(e["block"]) for e in used_memory) > memory_char_limit):
        used_memory.pop(0)
        memory_dropped += 1

    selected = list(prior_chapters[:k])                                       # ref: 最近 K 章
    dropped = 0
    while len(selected) > 1 and _total_len(selected) > char_limit:            # ref: R4：从更早的章丢（列表尾）
        selected.pop()
        dropped += 1

    canon_block = canon.strip() if canon and canon.strip() else "（暂无全书脉络）"
    mem_block = "".join(e["block"] + "\n" for e in used_memory) if used_memory else "（暂无近期条目）\n"
    ch_lines = []
    for c in reversed(selected):                                             # ref: 展示按章号升序
        ch_lines.append("### 第 %d 章 %s (slug: %s)\n%s\n" % (c["order"], c["title"], c["slug"], c["body"]))
    ch_block = "".join(ch_lines) if ch_lines else "（暂无前序章节原文）\n"
    if dropped:
        ch_block += "\n（注：因篇幅上限，已省略更早的 %d 章原文。）\n" % dropped

    context = (
        "【全书脉络（长期摘要）】\n" + canon_block + "\n\n"
        "【最近章节条目】\n" + mem_block +
        "\n【前序章节原文（最近 %d 章，按章号升序）】\n" % len(selected) + ch_block
    )
    stats = {"prior_hit": len(prior_chapters), "included": len(selected),
             "dropped": dropped, "memory_used": len(used_memory),
             "memory_dropped": memory_dropped,
             "memory_chars": sum(len(e["block"]) for e in used_memory),
             "canon_len": len(canon_block)}
    return context, stats


def prepare_followup(post, post_path, k, char_limit, memory_k, memory_char_limit):
    """主编排：解析当前章 series/order → 读记忆(+canon) → 扫前序 → 组装追更上下文。

    返回 dict（供 review_post 组 prompt / 打印摘要 / 更新记忆）。

    ref: plan §3 步骤1 数据流向（code_structure §3 一图流）
    """
    series_id = post.frontmatter.get("series")
    if not series_id:
        raise ValueError("prepare_followup 仅用于系列章节（frontmatter 缺 series）：%s" % post_path)
    order = _order_of(post.frontmatter, post_path)                            # ref: 当前章 order（显式容错）
    repo_root = resolve_repo_root(post_path)
    memory_text = load_memory(repo_root, series_id)
    canon = parse_canon(memory_text)                                          # ref: 全书脉络段（无 → ""）
    memory_entries = parse_memory_entries(memory_text)
    prior = scan_prior_chapters(repo_root, series_id, order)
    context, stats = build_context(memory_entries, canon, prior, order, k, char_limit,
                                   memory_k, memory_char_limit)
    return {
        "series_id": series_id,
        "order": order,
        "repo_root": repo_root,
        "memory_path": memory_path(repo_root, series_id),
        "context": context,
        "stats": stats,
        "k": k,
        "char_limit": char_limit,
        "canon": canon,
        "memory_k": memory_k,
        "memory_char_limit": memory_char_limit,
    }


def _render_entry(order, title, slug, digest_lines):
    """渲染单章记忆条目块（不含尾换行）。"""
    lines = ["## 第 %d 章 %s (slug: %s)" % (order, title, slug)]
    lines.extend(digest_lines)
    return "\n".join(lines)


def _split_memory(memory_text, series_id):
    """把记忆文件拆为 `(头部文本, 条目列表)`；无条目/空文件 → 用默认头部。

    🔴 **头部边界 = 首个章节条目标题 或 canon 标题**（取靠前者）——canon 段位于条目之前，
    若不以 canon 标题为界，canon 段会被并入头部 → 每次重写叠加一份 canon、`parse_canon` 恒读旧值
    （phase5 步骤4 离线冒烟实测所得；plan 未预见，见 implementation_notes §3 步骤4 意外）。
    ref: code_structure §6（头部 + 逐章条目）；phase5 plan §3 步骤1（canon 段）
    """
    entries = parse_memory_entries(memory_text)
    lines = memory_text.split("\n")
    idx = None
    for i, line in enumerate(lines):
        if _ENTRY_HEAD_RE.match(line) or line.strip().startswith(CANON_HEADING):
            idx = i
            break
    header = ("\n".join(lines[:idx]) if idx is not None else memory_text).strip()
    if not header:                                                            # ref: 新建文件 → 默认头部
        header = (_MEMORY_HEADER % series_id).strip()
    return header, entries


def update_memory(repo_root, series_id, order, title, slug, digest_lines, canon_text, memory_k):
    """为当前章**幂等**写入记忆条目 + 滚动重写 `## 全书脉络`（canon）。

    写盘结构 = `header + ## 全书脉络(canon) + 逐章条目`；条目按 `order`/`slug` 去重、升序。
    🔴 **仅当 `canon_text` 非空**才滚动丢弃旧条目（`entries[-memory_k:]`）——防「canon 写失败却丢条目 → 记忆丢失」
    （plan §8 红队点 R1）。

    ref: plan §3 步骤1（写盘结构 + canon 守卫滚动）；code_structure §4.1
    """
    path = memory_path(repo_root, series_id)
    header, entries = _split_memory(load_memory(repo_root, series_id), series_id)
    entries = [e for e in entries if not (e["order"] == order or e["slug"] == slug)]   # ref: 幂等去重
    entries.append({"order": order, "title": title, "slug": slug,
                    "block": _render_entry(order, title, slug, digest_lines)})
    entries.sort(key=lambda e: e["order"])                                    # ref: 章号升序
    canon = (canon_text or "").strip()
    if canon:                                                                 # ref: R1：仅 canon 非空才滚动丢弃
        entries = entries[-memory_k:]                                         # ref: 只留最近 M 条
    parts = [header, CANON_HEADING, canon if canon else "（暂无）"]
    parts.append("\n\n".join(e["block"] for e in entries))
    os.makedirs(os.path.dirname(path), exist_ok=True)                         # ref: data/series/ 可能不存在
    with open(path, "w", encoding="utf-8") as fh:                             # ref: 系统边界：写文件（--commit）
        fh.write("\n\n".join(parts) + "\n")
