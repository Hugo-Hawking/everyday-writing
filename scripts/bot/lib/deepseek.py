"""DeepSeek Chat Completions 封装（非流式，仅标准库）。

ref: reference/knowledge/github_platform/2026-10-02_平台接口实测.md §4（端点/认证/请求体/响应体/错误码）
ref: reference/plans/2026-10-02_phase1_端到端闭环/code_structure.md §3（DeepSeek 调用行）
"""

import json
import sys
import time
import urllib.error
import urllib.request

# ref: knowledge §4.1（OpenAI 兼容端点）
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
# ref: knowledge §4.2（model）
MODEL = "deepseek-chat"
# 显式传 temperature/max_tokens，规避「未实证·待运行时确认」的默认值
# ref: knowledge §4.2 / §6.4；主 Agent 硬性要求「显式传 temperature/max_tokens」
TEMPERATURE = 0.8
MAX_TOKENS = 2048
# 网络边界：请求超时（秒）
REQUEST_TIMEOUT = 60
# 429/5xx/超时 的退避间隔（秒），≤2 次
# ref: RULES §8（429/5xx/超时 → 退避重试 ≤2 次后放弃并记录原始响应）
RETRY_DELAYS = [2, 4]


def chat(api_key, messages):
    """调 DeepSeek，返回评论文本（choices[0].message.content）。

    ref: knowledge §4.3（取文本路径）
    """
    payload = {                                            # ref: knowledge §4.2 请求体
        "model": MODEL,
        "messages": messages,
        "stream": False,
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
    }
    data = json.dumps(payload).encode("utf-8")             # ref: 序列化请求体
    attempt = 0
    while True:
        try:
            req = urllib.request.Request(
                DEEPSEEK_URL,
                data=data,                                 # ref: POST body
                method="POST",
                headers={                                  # ref: knowledge §4.1 认证头
                    "Authorization": "Bearer " + api_key,
                    "Content-Type": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:   # ref: 发起请求
                body = resp.read().decode("utf-8")                               # ref: 读响应体
            return json.loads(body)["choices"][0]["message"]["content"]          # ref: knowledge §4.3
        except urllib.error.HTTPError as err:
            raw = err.read().decode("utf-8", "replace")    # ref: 保留原始响应体（RULES §8）
            if err.code == 429 or 500 <= err.code < 600:   # ref: 可重试码（RULES §8）
                if attempt < len(RETRY_DELAYS):
                    time.sleep(RETRY_DELAYS[attempt])      # ref: 退避
                    attempt += 1
                    continue
                _die("DeepSeek HTTP %d 退避重试 %d 次仍失败" % (err.code, len(RETRY_DELAYS)), raw)
            _die(_error_message(err.code), raw)            # ref: 不可重试 → 放弃并打印原始响应
        except OSError as err:                             # ref: 网络错误/超时（含 socket.timeout）
            if attempt < len(RETRY_DELAYS):
                time.sleep(RETRY_DELAYS[attempt])
                attempt += 1
                continue
            _die("DeepSeek 网络错误/超时，退避重试 %d 次仍失败" % len(RETRY_DELAYS), repr(err))


def _error_message(code):
    """按 RULES §8 / knowledge §4.4 给出不可重试错误的处置提示。"""
    if code == 401:
        return "DeepSeek 认证失败(401)：不重试，请核对 Secret DEEPSEEK_API_KEY 是否正确/已生效"  # ref: §4.4
    if code == 402:
        return "DeepSeek 余额不足(402)：不重试，请充值"                                            # ref: §4.4
    return "DeepSeek 请求被拒(%d)：不重试" % code                                                  # ref: §4.4


def _die(msg, raw):
    print("FATAL: %s\n原始响应: %s" % (msg, raw), file=sys.stderr)     # ref: RULES §8 记录原始响应
    sys.exit(1)
