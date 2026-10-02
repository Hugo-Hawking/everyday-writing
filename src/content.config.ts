// 内容集合 schema（posts）。
// ref: reference/plans/2026-10-02_phase1_端到端闭环/code_structure.md §2（content.config.ts 职责/字段）
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
  }),
});

export const collections = { posts };
