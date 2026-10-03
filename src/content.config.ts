// 内容集合 schema（posts + series）。
// ref: reference/plans/2026-10-02_phase1_端到端闭环/code_structure.md §2（content.config.ts 职责/字段）
// ref: reference/plans/2026-10-03_phase2_系列小说板块/code_structure.md §1/§5（posts 加 optional series/order；新增 series 集合）
// ref: node_modules/astro/types/content.d.ts:11（astro:content 导出 defineCollection）
// ref: node_modules/astro/types/content.d.ts:4（`z` 从 astro:content 导入已弃用，Astro 8 移除 → 用 astro/zod）
import { defineCollection } from 'astro:content';
import { glob } from 'astro/loaders';
import { z } from 'astro/zod';

// ref: node_modules/astro/dist/content/loaders/glob.d.ts:8（GlobOptions.pattern / .base）
// 条目 id 默认由文件路径 slug 化（glob.d.ts:14 generateId 默认实现），故文件名无需与 slug 字段一致；
// 路由以 frontmatter 的 slug 字段为准（RULES §1.5 三处一致性）。
const posts = defineCollection({
  loader: glob({ pattern: '**/*.md', base: './src/content/posts' }),
  schema: z.object({
    title: z.string(),
    date: z.coerce.date(),
    slug: z.string(),
    description: z.string(),
    tags: z.array(z.string()),
    // phase2：可选系列关联 + 章节号。**必须 optional**——现文 hello-world 无此二字段，设必填会让 astro build 失败。
    // ref: reference/plans/2026-10-03_phase2_系列小说板块/plan.md §3 步骤1 + §8 红队点 R1
    series: z.string().optional(), // 引用 src/content/series/<id>.md 的 id（= 文件名去扩展名）
    order: z.number().optional(), // 章节号；有 series 时必填（在 publish.yml/bot 侧校验，schema 不强绑）
  }),
});

// phase2：系列元数据集合。条目 id = 文件名去扩展名（= 系列标识）；frontmatter 无 slug 字段时
// generateIdDefault 回退为路径 slug（glob.js:11-30，源码实证）→ demo-novel.md → id "demo-novel"。
// ref: reference/plans/2026-10-03_phase2_系列小说板块/code_structure.md §5（series schema 拟定）
const series = defineCollection({
  loader: glob({ pattern: '**/*.md', base: './src/content/series' }),
  schema: z.object({
    title: z.string(),
    description: z.string().optional(),
    status: z.enum(['连载中', '完结']).default('连载中'), // zod/v4 default；ref: node_modules/astro/dist/zod.js:1
    cover: z.string().optional(),
  }),
});

export const collections = { posts, series };
