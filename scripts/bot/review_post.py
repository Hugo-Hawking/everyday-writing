"""主入口：读一篇文章 → 调 DeepSeek 生成评论 →（默认 dry-run）打印 / --commit 写入 Discussion。

用法：
    python scripts/bot/review_post.py --path src/content/posts/<file>.md            # dry-run（默认）
    python scripts/bot/review_post.py --path src/content/posts/<file>.md --commit   # 真写 GitHub

ref: reference/plans/2026-10-02_phase1_端到端闭环/plan.md §3 步骤 5
ref: reference/plans/2026-10-02_phase1_端到端闭环/code_structure.md §1/§2/§3/§4
"""

import argparse
import os
import sys

from lib import deepseek, github_graphql                    # ref: code_structure §1（scripts/bot/lib/）
from lib.md_parse import parse_post                         # ref: code_structure §2（md_parse.py）

# 常量（允许环境变量覆盖）；值为主 Agent 已确认实取（2026-10-02）
REPO = os.environ.get("GITHUB_REPOSITORY", "Hugo-Hawking/everyday-writing")          # ref: 裁定「已确认的常量」
REPO_ID = os.environ.get("GITHUB_REPOSITORY_ID", "R_kgDOU5AWOg")                     # ref: 常量（GraphQL repository.id）
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


def build_messages(post):
    """组 DeepSeek messages：system 角色设定 + user 文章内容。

    ref: knowledge/architecture §4（prompt 设计要点）
    """
    user_content = "文章标题：%s\n\n文章正文：\n%s" % (post.frontmatter.get("title", ""), post.body)   # ref: 正文喂给模型
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def main():
    parser = argparse.ArgumentParser(description="为单篇文章生成 DeepSeek 评论（默认 dry-run，不写 GitHub）。")
    parser.add_argument("--path", required=True, help="文章 md 路径")        # ref: 裁定（--path 必填）
    group = parser.add_mutually_exclusive_group()                            # ref: 裁定（--dry-run/--commit 互斥）
    group.add_argument("--dry-run", dest="commit", action="store_false", help="只打印评论（默认）")
    group.add_argument("--commit", dest="commit", action="store_true", help="真写 Discussion 评论")
    parser.set_defaults(commit=False)                                        # ref: 裁定 #5（默认 dry-run）
    args = parser.parse_args()

    try:
        post = parse_post(args.path)            # ref: 步骤 5 数据流向：md → frontmatter+body+slug
    except ValueError as err:
        _die(str(err))                          # ref: 裁定 #2（缺 slug/title 报错退出）

    messages = build_messages(post)             # ref: 组 prompt
    api_key = os.environ.get("DEEPSEEK_API_KEY")                    # ref: RULES §1.5（Secret 环境变量）
    if not api_key:
        _die("未设置环境变量 DEEPSEEK_API_KEY，无法调用 DeepSeek（请先 export 或配 Actions Secret）")   # ref: RULES §8

    comment = deepseek.chat(api_key, messages)  # ref: 步骤 5：调 DeepSeek 得评论文本

    if not args.commit:                         # ref: 裁定 #5（dry-run 短路，不碰 GraphQL）
        print("===== [dry-run] 文章 slug=%r 的评论 =====" % post.slug)
        print(comment)
        print("===== [dry-run] 结束：未调用 GitHub GraphQL（加 --commit 才写入）=====")
        return

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
        print("命中已存在的 Discussion id=%s（追加评论）" % discussion_id)                 # ref: 裁定 #6（命中仍追加）

    node = github_graphql.add_discussion_comment(token, discussion_id, comment)           # ref: 步骤 5：addDiscussionComment
    print("已写入评论 url=%s" % node["url"])


def _die(msg):
    print("FATAL: " + msg, file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
