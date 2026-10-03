"""一次性探针（phase4 诊断，用完即删）：GITHUB_TOKEN（GitHub Actions App 身份）
对 Discussion 评论的 update / delete 能力。对应 smoke discussion #11 = D_kwDOU5AWOs4Apvcg。

只读/自清理：只更新/删除「本探针自己新建的那条」，不碰 bot 既有评论与人类评论。
"""

import json
import os
import urllib.error
import urllib.request

URL = "https://api.github.com/graphql"
TOKEN = os.environ["GITHUB_TOKEN"]
DISC = "D_kwDOU5AWOs4Apvcg"                    # smoke discussion #11
BOT_COMMENT = "DC_kwDOU5AWOs4BHcmh"            # 该 discussion 里 bot 既有评论


def call(query, variables):
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(URL, data=body, method="POST", headers={
        "Authorization": "Bearer " + TOKEN,
        "Content-Type": "application/json",
        "User-Agent": "probe",
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as err:
        return {"__http_error__": err.code, "body": err.read().decode("utf-8", "replace")}


UPDATE = """mutation($input: UpdateDiscussionCommentInput!){
  updateDiscussionComment(input:$input){ comment{ id url } } }"""
DELETE = """mutation($input: DeleteDiscussionCommentInput!){
  deleteDiscussionComment(input:$input){ comment{ id } } }"""
ADD = """mutation($input: AddDiscussionCommentInput!){
  addDiscussionComment(input:$input){ comment{ id author{ login } } } }"""

print("[1] update 既有 bot 评论 :", call(UPDATE, {"input": {"commentId": BOT_COMMENT, "body": "probe-update-existing"}}))

added = call(ADD, {"input": {"discussionId": DISC, "body": "probe temp comment (自清理)"}})
print("[2] add 新评论           :", added)
cid = added.get("data", {}).get("addDiscussionComment", {}).get("comment", {}).get("id")

if cid:
    print("[3] update 本轮新建评论  :", call(UPDATE, {"input": {"commentId": cid, "body": "probe temp comment v2"}}))
    print("[4] delete 本轮新建评论  :", call(DELETE, {"input": {"id": cid}}))
else:
    print("[3]/[4] 跳过（新建未成功）")
