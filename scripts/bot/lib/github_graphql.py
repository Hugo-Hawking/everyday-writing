"""GitHub Discussions GraphQL 封装：找库 / 建库 / 加评论（仅标准库）。

每次调用 = 单个 POST https://api.github.com/graphql，body {query, variables}，头 Bearer。
不做重试：GraphQL 写操作重试可能造成重复建库/重复评论。

ref: reference/knowledge/github_platform/2026-10-02_平台接口实测.md §3（GraphQL Discussions 字段实证）
ref: reference/plans/2026-10-02_phase1_端到端闭环/code_structure.md §3（建 Discussion / 加评论 / 找 Discussion）
"""

import json
import sys
import urllib.error
import urllib.request

GRAPHQL_URL = "https://api.github.com/graphql"     # ref: knowledge §3（GraphQL 单一端点）
REQUEST_TIMEOUT = 60                               # ref: 网络边界：请求超时（秒）

# 按标题找库：search(type:DISCUSSION)，取 nodes 内 Discussion 的 id/title/category
# ref: knowledge §3.3-1（giscus 采用 search 找库）
_FIND_QUERY = """
query($q: String!) {
  search(type: DISCUSSION, last: 1, query: $q) {
    nodes { ... on Discussion { id title category { id } } }
  }
}
"""

# ref: knowledge §3.1（createDiscussion）
_CREATE_QUERY = """
mutation($input: CreateDiscussionInput!) {
  createDiscussion(input: $input) {
    discussion { id url }
  }
}
"""

# ref: knowledge §3.2（addDiscussionComment）
_COMMENT_QUERY = """
mutation($input: AddDiscussionCommentInput!) {
  addDiscussionComment(input: $input) {
    comment { id url }
  }
}
"""


def find_discussion(token, repo, slug, category_id):
    """按标题找本文章的 Discussion；命中需标题相等且分类 id 一致，否则返回 None。

    ref: 主 Agent 裁定 #4（不用 category: 搜索限定符；搜后校验 title 与 category.id 双条件）
    ref: knowledge §3.3-1（in:title 为模糊搜索，须自行校验 nodes[0].title）
    """
    query = 'repo:%s in:title "%s"' % (repo.lower(), slug)   # ref: knowledge §2.3（repo 小写）
    data = _graphql(token, _FIND_QUERY, {"q": query})
    nodes = data["search"]["nodes"]                          # ref: knowledge §3.3-1（取 nodes）
    if not nodes:
        return None
    node = nodes[0]                                          # ref: last:1 → 取首元素
    if node["title"] == slug and node["category"]["id"] == category_id:   # ref: 裁定 #4 双条件命中
        return node["id"]
    return None


def create_discussion(token, repo_id, category_id, title, body):
    """建 Discussion（标题 = slug）；返回 {id, url}。

    ref: knowledge §3.1（input: repositoryId/categoryId/title/body；返回 discussion{id,url}）
    """
    data = _graphql(token, _CREATE_QUERY, {"input": {
        "repositoryId": repo_id,
        "categoryId": category_id,
        "title": title,
        "body": body,
    }})
    return data["createDiscussion"]["discussion"]            # ref: knowledge §3.1（返回路径）


def add_discussion_comment(token, discussion_id, body):
    """给 Discussion 加顶层评论（缺省 replyToId）；返回 {id, url}。

    ref: knowledge §3.2（input: discussionId/body；返回 comment{id,url}）
    """
    data = _graphql(token, _COMMENT_QUERY, {"input": {
        "discussionId": discussion_id,
        "body": body,
    }})
    return data["addDiscussionComment"]["comment"]           # ref: knowledge §3.2（返回路径）


def _graphql(token, query, variables):
    """POST GraphQL 端点，返回 data 段。错误按 RULES §8 处理（无重试）。"""
    payload = json.dumps({"query": query, "variables": variables}).encode("utf-8")   # ref: knowledge §3 调用约定
    req = urllib.request.Request(
        GRAPHQL_URL,
        data=payload,
        method="POST",
        headers={
            "Authorization": "Bearer " + token,             # ref: RULES §1.5（GITHUB_TOKEN）
            "Content-Type": "application/json",
            "User-Agent": "everyday-writing-bot",           # ref: GitHub API 要求 UA
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as err:
        raw = err.read().decode("utf-8", "replace")         # ref: 保留原始响应（RULES §8）
        if err.code == 403:
            _die("GraphQL 403：请先检查 workflow 是否声明 permissions: discussions: write（RULES §1.5/§8）", raw)
        if err.code == 401:
            _die("GraphQL 401：GITHUB_TOKEN 无效或缺失", raw)
        _die("GraphQL HTTP %d" % err.code, raw)             # ref: 其余错误快速失败
    result = json.loads(body)
    if result.get("errors"):                                # ref: GraphQL 层错误（HTTP 200 内含 errors）
        _die("GraphQL 返回 errors", json.dumps(result["errors"], ensure_ascii=False))
    return result["data"]                                   # ref: knowledge §3（{data:{...}} 形态）


def _die(msg, raw):
    print("FATAL: %s\n原始响应: %s" % (msg, raw), file=sys.stderr)
    sys.exit(1)
