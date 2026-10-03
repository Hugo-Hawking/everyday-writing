"""主入口：读一篇文章 → 调 DeepSeek 生成评论 →（默认 dry-run）打印 / --commit 写入 Discussion。

用法：
    python scripts/bot/review_post.py --path src/content/posts/<file>.md            # dry-run（默认）
    python scripts/bot/review_post.py --path src/content/posts/<file>.md --commit   # 真写 GitHub
    python scripts/bot/review_post.py --path src/content/posts/<file>.md --show-context   # 只打印 messages（不调模型）

系列章节（frontmatter 含 `series`）：走「追更」路径，**两次 DeepSeek 调用**——
  第一次（评论）：system=追更读者+前情记忆，user=最近 K 章原文+当前章正文 → 评论正文（发 Discussion）；
  第二次（记忆）：system=记忆指令，user 同上（与评论调用同源，立足原文）→ 当前章记忆条目正文
  （写入 `data/series/<系列>.md`）。
dry-run/--show-context 均不写记忆文件；--commit 才写（git 提交由 workflow 完成，见 plan 步骤 6）。
非系列文章走原有路径（不回归）。

ref: reference/plans/2026-10-02_phase1_端到端闭环/plan.md §3 步骤 5
ref: reference/plans/2026-10-02_phase1_端到端闭环/code_structure.md §1/§2/§3/§4
ref: reference/plans/2026-10-03_phase2_系列小说板块/plan.md §3 步骤 5
"""

import argparse
import os
import sys

from lib import deepseek, github_graphql, series            # ref: code_structure §1（scripts/bot/lib/）
from lib.md_parse import parse_post                         # ref: code_structure §2（md_parse.py）

# 常量（允许环境变量覆盖）；值为主 Agent 已确认实取（2026-10-02）
REPO = os.environ.get("GITHUB_REPOSITORY", "Hugo-Hawking/everyday-writing")          # ref: 裁定「已确认的常量」
# ⚠️ 本变量的环境变量名必须带项目前缀 DISCUSSIONS_，切勿改回 GITHUB_REPOSITORY_ID：
#    GitHub Actions 会自动注入保留环境变量 GITHUB_REPOSITORY_ID=<数字仓库 id>（如 1401951802），
#    与本项目 GraphQL 需要的「全局 node id」（如 R_kgDOU5AWOg）语义不同；同名会让平台注入值
#    覆盖默认值，导致 createDiscussion 报 NOT_FOUND: Could not resolve to a node with the global id of '<数字>'。
#    ref: 步骤 6 冒烟失败根因（run 37026079399）；与下方 DISCUSSIONS_CATEGORY_* 保持同前缀。
REPO_ID = os.environ.get("DISCUSSIONS_REPO_ID", "R_kgDOU5AWOg")                      # ref: 常量（GraphQL repository.id）
CATEGORY_NAME = os.environ.get("DISCUSSIONS_CATEGORY_NAME", "General")               # ref: 常量（giscus data-category 须与此同）
CATEGORY_ID = os.environ.get("DISCUSSIONS_CATEGORY_ID", "DIC_kwDOU5AWOs4DG48K")      # ref: 常量（General 分类 node id）

# 新建 Discussion 的占位正文（真评论随后以 comment 追加）
# ref: knowledge §2.3（Discussion 标题 = term；body 供承载评论）
DISCUSSION_PLACEHOLDER_BODY = "本 Discussion 承载该文章的读者评论，由 everyday-writing bot 自动创建。\n"

# ref: reference/knowledge/architecture/2026-10-02_架构决策.md §4（bot 评论文本格式 + prompt 设计要点）
SYSTEM_PROMPT = (
    "你是「everyday-writing」写作网站的 AI 评论 bot，定位是一位真诚、敏锐的读者，而不是奉承者。\n"
    "请用中文为下面这篇文章写一段读后评论，严格按以下 Markdown 结构输出：\n\n"
    "> 🤖 DeepSeek 自动评论\n\n"
    "## 读后感想\n"
    "（整体感受，2-4 句）\n\n"
    "## 写得好的地方\n"
    "- （引用原文的具体片段，指出亮点，1-3 条）\n\n"
    "## 可以改进的地方\n"
    "- （具体、可操作的建议，1-3 条）\n\n"
    "要求：必须引用原文中的具体词句；改进建议要具体可操作；不要空泛的客套鼓励。"
)

# 追更路径（第一次调用）system prompt：追更读者角色 + 前情记忆；输出**就是评论文本本体**，
# 不含任何记忆块（记忆由第二次调用单独生成，见 MEMORY_SYSTEM_PROMPT）。
# ref: plan §3 步骤5（system=追更读者角色+前情记忆；user=最近K章+当前章正文）
# ref: code_structure §4 数据流（追更式评论文本供 addDiscussionComment）
FOLLOWUP_SYSTEM_PROMPT = (
    "你是「everyday-writing」写作网站的 AI 评论 bot，正在**追更**一部连载小说。你的定位是一位真诚、敏锐的追更读者，而不是奉承者。\n"
    "你会看到该系列**此前章节的追更记忆**与**最近若干章原文**；请据此为**当前这一章**写评论，体现「一直在追读」的连续视角：\n"
    "结合前情记忆与前序章节，呼应前文的人物、情节或伏笔；但**不得臆造**前文/当前章未出现的内容。\n\n"
    "请严格按以下 Markdown 结构输出：\n\n"
    "> 🤖 DeepSeek 自动评论\n\n"
    "## 读后感想\n"
    "（结合前情与本章，2-4 句）\n\n"
    "## 写得好的地方\n"
    "- （引用本章或前文的具体片段，1-3 条）\n\n"
    "## 可以改进的地方\n"
    "- （具体、可操作的建议，1-3 条）\n\n"
    "要求：必须引用原文中的具体词句；不得臆造；不要空泛的客套鼓励。"
)

# 记忆路径（第二次调用）system prompt：只产出**当前章**的记忆条目正文（供 update_memory 落盘），
# 不产出评论、不含 Markdown 标题、不含解释。
# ref: plan §3 步骤5（记忆条目来源 = 二次调用，主 Agent 2026-10-03 裁定）
# ref: code_structure §6（记忆条目格式：- 梗概 / - 人物·伏笔）
MEMORY_SYSTEM_PROMPT = (
    "你是「everyday-writing」写作网站的追更记忆整理器。你会看到某部连载小说的前情记忆、"
    "此前章节原文，以及**当前这一章**正文。\n"
    "请只为**当前这一章**生成追更记忆条目正文，供系统存档（不对外展示）。严格按以下格式输出，"
    "不要输出评论、不要 Markdown 标题、不要任何解释：\n\n"
    "- 梗概：（本章 1-3 句剧情梗概）\n"
    "- 人物/伏笔：（本章新增或推进的人物与伏笔；若无，省略此行）\n\n"
    "要求：只依据前文与当前章实际出现的内容，不得臆造；梗概须抓住本章关键情节。"
)


def _normalize_digest_lines(digest):
    """把记忆块正文规整为以 `- ` 起头的行列表（= 记忆条目正文行）。"""
    lines = []
    for ln in digest.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        lines.append(ln if ln.startswith("-") else "- " + ln)
    return lines


def _print_context(post, followup, comment_messages, memory_messages):
    """`--show-context`：打印组装好的 messages（不调模型、不写文件），供离线核对。

    系列章节同时打印**评论用**与**记忆用**两组 messages（标注清楚）；非系列只打印评论用。
    """
    if followup:
        s = followup["stats"]
        print("===== [show-context] 追更上下文摘要（未调用模型）=====")
        print("系列 id        : %s" % followup["series_id"])
        print("当前章 order   : %d" % followup["order"])
        print("前序章节命中数 : %d" % s["prior_hit"])
        print("纳入章数       : %d（K=%d，上限 %d 字符）" % (s["included"], followup["k"], followup["char_limit"]))
        print("因长度丢弃章数 : %d" % s["dropped"])
        print("记忆条目数     : %d（order<当前）" % s["memory_used"])
        print("记忆文件       : %s" % followup["memory_path"])
        print("===== [show-context] 评论用 messages（第一次调用）=====")
    else:
        print("===== [show-context] 非系列文章，走原路径（仅评论用 messages）=====")
    for i, msg in enumerate(comment_messages):
        print("--- messages[%d] role=%s ---" % (i, msg["role"]))
        print(msg["content"])
    if memory_messages:                          # ref: 步骤5：记忆=二次调用，单独打印核对
        print("===== [show-context] 记忆用 messages（第二次调用）=====")
        for i, msg in enumerate(memory_messages):
            print("--- messages[%d] role=%s ---" % (i, msg["role"]))
            print(msg["content"])
    print("===== [show-context] 结束（未调用模型、未写任何文件）=====")


def _print_dry_run(post, followup, comment, digest_lines):
    """dry-run 打印：追更上下文摘要（若有）+ 评论文本 + 记忆条目预览（不落盘）。"""
    if followup:
        s = followup["stats"]
        print("===== [dry-run] 追更上下文摘要 =====")
        print("系列 id        : %s" % followup["series_id"])
        print("当前章 order   : %d" % followup["order"])
        print("前序章节命中数 : %d" % s["prior_hit"])
        print("纳入章数       : %d（K=%d，上限 %d 字符）" % (s["included"], followup["k"], followup["char_limit"]))
        print("因长度丢弃章数 : %d" % s["dropped"])
        print("记忆条目数     : %d（order<当前）" % s["memory_used"])
        print("===================================")
    print("===== [dry-run] 文章 slug=%r 的评论 =====" % post.slug)
    print(comment)
    if followup:
        print("----- [dry-run] 追更记忆条目（不落盘）-----")
        print("\n".join(digest_lines) if digest_lines else "（模型未输出记忆条目）")
    print("===== [dry-run] 结束：未调用 GitHub GraphQL、未写记忆文件 =====")


def build_messages(post):
    """组 DeepSeek messages：system 角色设定 + user 文章内容。

    ref: knowledge/architecture §4（prompt 设计要点）
    """
    user_content = "文章标题：%s\n\n文章正文：\n%s" % (post.frontmatter.get("title", ""), post.body)   # ref: 正文喂给模型
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def build_followup_messages(followup, post):
    """追更路径（第一次调用）messages：user = 追更上下文（记忆+前序章节） + 当前章正文。

    ref: plan §3 步骤5（user=最近K章原文+当前章正文）
    """
    user_content = (
        followup["context"] +
        "\n\n当前章（第 %d 章）\n文章标题：%s\n\n文章正文：\n%s"
        % (followup["order"], post.frontmatter.get("title", ""), post.body)
    )
    return [
        {"role": "system", "content": FOLLOWUP_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def build_memory_messages(followup, post):
    """记忆路径（第二次调用）messages：user 与评论调用**同源**（追更上下文+当前章正文），

    保证记忆同样「立足原文」；system = 记忆指令（只产出记忆条目正文）。

    ref: plan §3 步骤5（记忆条目来源 = 二次调用）
    ref: code_structure §6（记忆条目格式）
    """
    user_content = (
        followup["context"] +
        "\n\n当前章（第 %d 章）\n文章标题：%s\n\n文章正文：\n%s"
        % (followup["order"], post.frontmatter.get("title", ""), post.body)
    )
    return [
        {"role": "system", "content": MEMORY_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def pick_bot_comments(comments, bot_author):
    """从 comments 里挑出 bot 自己的评论，按 createdAt 倒序（最新在前）。

    纯函数：不触网、不依赖返回顺序（comments 无 orderBy）。
    ref: plan §8 R5（本地倒序，避免信任返回顺序取错「最新」）
    ref: plan §8 R1/R2（仅按 login 精确过滤 → 人类评论永不被选中）
    """
    bots = [c for c in comments if c.get("login") == bot_author]
    bots.sort(key=lambda c: c.get("created_at", ""), reverse=True)   # ISO8601 字典序==时间序
    return bots


def main():
    parser = argparse.ArgumentParser(description="为单篇文章生成 DeepSeek 评论（默认 dry-run，不写 GitHub）。")
    parser.add_argument("--path", required=True, help="文章 md 路径")        # ref: 裁定（--path 必填）
    group = parser.add_mutually_exclusive_group()                            # ref: 裁定（--dry-run/--commit 互斥）
    group.add_argument("--dry-run", dest="commit", action="store_false", help="只打印评论（默认）")
    group.add_argument("--commit", dest="commit", action="store_true", help="真写 Discussion 评论")
    parser.set_defaults(commit=False)                                        # ref: 裁定 #5（默认 dry-run）
    # 步骤 5 新增：离线核对上下文（不调模型、不写文件）
    parser.add_argument("--show-context", action="store_true",
                        help="只打印组装好的 messages（不调用模型、不写文件），供离线核对追更上下文")
    parser.add_argument("--context-k", type=int, default=None,
                        help="追更上下文纳入的最近章数（默认 %d，可被环境变量 SERIES_CONTEXT_K 覆盖）" % series.DEFAULT_K)
    args = parser.parse_args()

    # 追更上下文的 K 与字符上限（plan §3 步骤5：K 默认 10 可配置；上限防红队点 R4）
    k = args.context_k if args.context_k is not None else int(os.environ.get("SERIES_CONTEXT_K", series.DEFAULT_K))
    char_limit = int(os.environ.get("SERIES_CONTEXT_CHAR_LIMIT", series.DEFAULT_CHAR_LIMIT))

    try:
        post = parse_post(args.path)            # ref: 步骤 5 数据流向：md → frontmatter+body+slug
    except ValueError as err:
        _die(str(err))                          # ref: 裁定 #2（缺 slug/title 报错退出）

    followup = None
    memory_messages = None
    if post.frontmatter.get("series"):          # ref: 步骤5：系列章节走追更路径，否则原路径（不回归）
        try:
            followup = series.prepare_followup(post, args.path, k, char_limit)
        except ValueError as err:               # ref: 步骤5 关键坑（缺/非法 order 显式报错）
            _die(str(err))
        comment_messages = build_followup_messages(followup, post)
        memory_messages = build_memory_messages(followup, post)   # ref: 步骤5：记忆条目走二次调用
    else:
        comment_messages = build_messages(post)  # ref: 非系列不回归

    if args.show_context:                       # ref: 离线自检路径：不调模型、不写文件
        _print_context(post, followup, comment_messages, memory_messages)
        return

    api_key = os.environ.get("DEEPSEEK_API_KEY")                    # ref: RULES §1.5（Secret 环境变量）
    if not api_key:
        _die("未设置环境变量 DEEPSEEK_API_KEY，无法调用 DeepSeek（请先 export 或配 Actions Secret）")   # ref: RULES §8

    comment = deepseek.chat(api_key, comment_messages)   # 第一次调用：追更评论正文（ref: 步骤5）

    digest_lines = None
    if followup:
        # 第二次调用：生成当前章记忆条目正文。**先于「发评论」生成**——生成失败时 deepseek.chat 内部
        # 直接退出（sys.exit），从而避免「评论已发但记忆失败」的半完成态（主 Agent 2026-10-03 裁定，
        # notes「设计短注 §5」决策1）。故此处位于 add_discussion_comment 之前。
        raw_digest = deepseek.chat(api_key, memory_messages)     # ref: 步骤5（记忆=二次调用）
        digest_lines = _normalize_digest_lines(raw_digest)       # ref: 复用规整（- 起头的行列表）

    if not args.commit:                         # ref: 裁定 #5（dry-run 短路，不碰 GraphQL/记忆文件）
        _print_dry_run(post, followup, comment, digest_lines)
        return

    if followup and not digest_lines:           # ref: RULES §12.6（--commit 缺记忆条目快速失败，不静默降级）
        _die("系列章节记忆条目为空，已中止：--commit 需非空记忆条目才能更新记忆文件")

    token = os.environ.get("GITHUB_TOKEN")      # ref: RULES §1.5（Actions 内自动 token）
    if not token:
        _die("--commit 需要环境变量 GITHUB_TOKEN（需 discussions:write 权限）")   # ref: RULES §8

    print("目标分类：%s（id=%s）" % (CATEGORY_NAME, CATEGORY_ID))   # ref: 常量（日志便于核对与 giscus 一致）

    discussion_id = github_graphql.find_discussion(token, REPO, post.slug, CATEGORY_ID)   # ref: 裁定 #4
    if discussion_id is None:
        discussion = github_graphql.create_discussion(
            token, REPO_ID, CATEGORY_ID, post.slug, DISCUSSION_PLACEHOLDER_BODY)          # ref: 裁定 #4（未命中→建库）
        discussion_id = discussion["id"]
        print("已创建 Discussion 标题=%r url=%s" % (post.slug, discussion["url"]))
    else:
        print("命中已存在的 Discussion id=%s（将更新既有评论）" % discussion_id)           # ref: plan §3 步骤2（命中→更新）

    # 评论落库策略：更新优先 → 缺失则新增 → 收敛历史 bot 重复条（人类评论永不触碰）。
    # 识别 bot 评论只用 author.login，**不得用 viewerDidAuthor**——本机以 OAuth 身份查询 bot 评论时该字段
    # 恒为 false（ref: plan §4 假设2，Discussion #8 2026-10-03 实测）。
    # ref: plan §3 步骤2；code_structure §2.2
    bot_comments = pick_bot_comments(
        github_graphql.list_discussion_comments(token, discussion_id),
        github_graphql.BOT_COMMENT_AUTHOR,
    )
    if bot_comments:
        newest = bot_comments[0]                                                          # 倒序首条 = 最新
        node = github_graphql.update_discussion_comment(token, newest["id"], comment)     # 原地覆盖（先更新）
        print("已更新既有评论 id=%s url=%s" % (newest["id"], node["url"]))
        for old in bot_comments[1:]:                                                      # 仅删更旧的 bot 重复条（后删除）
            github_graphql.delete_discussion_comment(token, old["id"])
            print("已删除 bot 重复评论 id=%s" % old["id"])
    else:
        node = github_graphql.add_discussion_comment(token, discussion_id, comment)       # 无 bot 评论 → 新增
        print("已写入评论 url=%s" % node["url"])

    if followup:                                # ref: 步骤5：评论成功后幂等更新记忆文件（git 提交归步骤6）
        series.update_memory(
            followup["repo_root"], followup["series_id"], followup["order"],
            post.frontmatter.get("title", ""), post.slug, digest_lines)   # ref: 二次调用产出的条目行
        print("已更新追更记忆文件 %s" % followup["memory_path"])


def _die(msg):
    print("FATAL: " + msg, file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
