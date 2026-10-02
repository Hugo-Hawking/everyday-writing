"""解析文章 Markdown：拆 frontmatter 与正文，取 slug。仅标准库。

frontmatter 约定（本项目文章）：文件以 '---' 起止包裹，内部为逐行 `key: value`；
`tags` 支持内联 `[a, b]` 与逐行 `- x` 两种写法，其余键按字符串。

ref: reference/plans/2026-10-02_phase1_端到端闭环/code_structure.md §2（md_parse.py 职责：解析 frontmatter + 正文）
ref: reference/knowledge/architecture/2026-10-02_架构决策.md §5（frontmatter 字段 title/date/slug/description/tags）
"""


class Post(object):
    """一篇文章：frontmatter 字典 + 正文 + slug（= frontmatter['slug']）。

    ref: reference/plans/2026-10-02_phase1_端到端闭环/code_structure.md §4（Discussion 标题 = frontmatter slug）
    """

    def __init__(self, frontmatter, body, slug):
        self.frontmatter = frontmatter
        self.body = body
        self.slug = slug


def parse_post(path):
    """读 md 文件 → Post。缺 slug/title 时报错退出（不静默、不默认）。

    ref: 主 Agent 裁定 #1/#2（手写 frontmatter 解析；缺 slug/title 报错退出）
    """
    with open(path, "r", encoding="utf-8") as fh:          # ref: 系统边界：读文件（RULES §12.2）
        text = fh.read()                                   # ref: 一次性读入文本
    frontmatter, body = _split_frontmatter(text, path)     # ref: 拆 frontmatter/正文
    slug = frontmatter.get("slug")                         # ref: code_structure §4 铁律：slug 为 URL/term/标题来源
    if not slug:
        raise ValueError("frontmatter 缺少必填字段 'slug'：%s" % path)    # ref: 裁定 #2
    if not frontmatter.get("title"):
        raise ValueError("frontmatter 缺少必填字段 'title'：%s" % path)   # ref: 裁定 #2
    return Post(frontmatter, body, slug)


def _split_frontmatter(text, path):
    """把 '---\\n...\\n---\\n正文' 拆成 (frontmatter dict, body str)。

    ref: reference/plans/2026-10-02_phase1_端到端闭环/implementation_notes.md 设计短注 ③
         （'---' 分隔 + 逐行 key: value，自写解析，不引 PyYAML）
    """
    lines = text.split("\n")                               # ref: 按行切分
    if not lines or lines[0].strip() != "---":             # ref: 边界校验：必须以 frontmatter 起始行开头
        raise ValueError("文件未以 frontmatter 起始 '---' 开头：%s" % path)
    end = None
    for i in range(1, len(lines)):                         # ref: 找收尾分隔行
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:                                        # ref: 边界校验：未闭合
        raise ValueError("frontmatter 未闭合（缺收尾 '---'）：%s" % path)
    frontmatter = _parse_pairs(lines[1:end])               # ref: 解析分隔行之间的键值
    body = "\n".join(lines[end + 1:]).strip("\n")          # ref: 正文 = 收尾分隔行之后
    return frontmatter, body


def _parse_pairs(lines):
    """逐行解析 frontmatter：内联列表 `[a, b]`、逐行列表 `- x`、其余按字符串。

    ref: 主 Agent 裁定 #1（手写 frontmatter 解析）
    """
    fm = {}
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped:                                   # ref: 跳过空行
            i += 1
            continue
        if ":" not in stripped:                            # ref: 边界校验：非法行
            raise ValueError("frontmatter 行格式非法（缺 ':'）：%r" % lines[i])
        key, _, value = stripped.partition(":")            # ref: 按首个 ':' 拆 key/value
        key = key.strip()
        value = value.strip()
        if value == "":                                    # ref: 值为空 → 可能是逐行列表
            items = []
            j = i + 1
            while j < len(lines) and lines[j].strip().startswith("- "):   # ref: 逐行列表项 '- x'
                items.append(lines[j].strip()[2:].strip())
                j += 1
            if items:
                fm[key] = items                            # ref: 逐行列表写法
                i = j
                continue
            fm[key] = ""                                   # ref: 普通空字符串字段
            i += 1
            continue
        if value.startswith("[") and value.endswith("]"):  # ref: 内联列表写法 `[a, b]`
            inner = value[1:-1].strip()
            fm[key] = [x.strip() for x in inner.split(",") if x.strip()] if inner else []
        else:
            fm[key] = value                                # ref: 其余按字符串（裁定 #1）
        i += 1
    return fm
