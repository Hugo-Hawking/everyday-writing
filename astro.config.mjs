// @ts-check
import { defineConfig } from 'astro/config';

// GitHub Pages 项目站配置。
// ref: reference/plans/2026-10-02_phase1_端到端闭环/plan.md §3 步骤1（site/base 定死，后续 URL 与 giscus pathname 全依赖它）
export default defineConfig({
  site: 'https://hugo-hawking.github.io',
  base: '/everyday-writing/',
  // 确定性尾斜杠：让页面 pathname 恒以 `/` 结尾，避免 giscus mapping=pathname 因尾斜杠歧义错配。
  // ref: node_modules/astro/dist/core/config/schemas/base.js:45（合法值 'always'|'never'|'ignore'，默认 'ignore'）
  // ref: node_modules/astro/dist/core/config/schemas/relative.js:76（'always' → base 规范为 prepend+append 斜杠）
  trailingSlash: 'always',
});
