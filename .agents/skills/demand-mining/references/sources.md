# 站点采集手册

通用规则：

- 按各站标注的访问阶梯执行；`L1`=WebFetch/API，`L2`=内置浏览器，`L3`=用户本机 Chrome
- 配额：每站最多 `limits.max_signals_per_source`（默认 30）条，只收高置信条目
- Cloudflare 挑战页：等 5 秒重载一次；再失败记 `failed` 进 site_status，不要反复硬闯——换时段重跑比强攻有效
- 429/403：退避 30 秒重试一次，仍失败则降级到下一访问阶梯
- 任何站点单轮最多访问 3 个页面（入口 + 1~2 个翻页/榜单），够配额即停

## 1. Toolify（toolify.ai）→ new_product / revenue

- 入口（实测 2026-09-13）：**新站列表是 `https://www.toolify.ai/new`**（`/site/new` 是 404，别用）；收入榜 `https://www.toolify.ai/Best-AI-Tools-revenue`
- 访问：L2。首次加载会出 Cloudflare 挑战页，等 6 秒 reload 一次即过（内置浏览器可过）；goto 超时 10 秒属正常，页面实际会加载完，重观察即可，不要重试导航
- 新站抽取：卡片选择器 `a[href^="/tool/"]`，取 innerText 第一行做 name、后续行做定位语；需 IIFE 包裹 evaluate 脚本
- 收入榜注意（实测）：榜单是全量排行（第一屏全是 ChatGPT/Claude 等巨头），**无"新进榜"标识且卡片不渲染收入数字**——本轮直接跳过；等积累 2 轮以上数据后做跨轮 diff 才有意义
- 懒加载：页面滚动加载，evaluate 里 `window.scrollTo(0, document.body.scrollHeight)` 后等 2 秒再抽取

## 2. Reddit → complaint / request / alternative

- **本机实测（2026-09-13）：JSON API 即使走代理也被拦（返回 HTML 拦截页），curl 抓 old.reddit HTML 也被 302 重定向。Reddit 只有 L3 真实浏览器一条路。**
- 入口（L3）：后台窗口打开 `https://old.reddit.com/r/<sub>/search?q=<关键词>&restrict_sr=on&sort=new&t=week`（old.reddit 服务端渲染，execute JS 可解析）
- 提取 JS 模板（已验证可用）：
  `Array.from(document.querySelectorAll('.search-result-link')).map(e=>{const t=e.querySelector('.search-title');const l=e.querySelector('.search-comments');const m=e.querySelector('.search-result-meta');return (t?t.innerText:'')+' || '+(l&&l.href?l.href:'')+' || '+(m?m.innerText.replace(/\\n/g,' '):'')}).join('\\n')`
- 子版与关键词来自 `sources.json` → `profiles.<当前profile>.subreddits` 与 `reddit.keywords`
- 看什么：标题含"looking for / alternative to / is there a tool / how do I / recommend / too expensive / any app"等求助或抱怨的帖子
- 抽取：quote = 帖子标题（+selftext 前 150 字符，有则拼上）；source_url = 帖子 permalink；entity = 帖子在找的东西或被抱怨的对象（工具名或任务短语），不要抄整句标题当 entity
- emotion 映射：抱怨 → negative；求推荐/怎么完成 → asking
- 每个子版×关键词组合最多取 `limits.max_reddit_per_combo`（默认 8）条

## 3. GitHub → new_product

- 入口（L1）：`https://github.com/trending?since=daily`；可选 API：`https://api.github.com/search/repositories?q=created:>2026-09-06+stars:>50&sort=stars&per_page=30`（日期取 7 天前）
- 看什么：Trending 新仓库、新星数急涨的新仓库
- 抽取：entity = 仓库名去掉 owner 前缀；quote = repo 描述；source_url = 仓库链接
- Issues 里的 feature request 抽取为 P1，本轮不做

## 4. Hacker News → new_product / request

- 入口（L1）：`https://hn.algolia.com/api/v1/search_by_date?tags=(show_hn,ask_hn)&hitsPerPage=30&numericFilters=points>5`
- 只取 `created_at` 在最近 48 小时内的命中
- Show HN → new_product（entity 从标题抽产品名）；Ask HN 里求工具/求方案 → request（entity = 问题对象）
- quote = title；source_url = `https://news.ycombinator.com/item?id=<objectID>`

## 5. App Store 竞品评论 → complaint

- 入口（L1）：`https://itunes.apple.com/<country>/rss/customerreviews/id=<app_id>/sortby=mostrecent/page=1/json`
- `sources.json → appstore.app_ids` 为空则整站跳过（status=skipped）
- 只收星级 ≤3 的评论：quote = 评论原文（≤200字符）；entity = 被评论的 App 名或评论指出的缺陷对象（取更具体者）
- emotion 一律 negative

## 6. Google Trends → trend

- 入口（L2）：`https://trends.google.com/trending?geo=<trends_geo>`（实时趋势）；飙升查询需进 explore 页面按 profile 词根逐个查
- 页面 JS 依赖重，domSnapshot 读不到时用 CUA 截图判读关键榜单数字
- 看什么：与当前 profile 相关的飙升词/热词；entity = 词本身；quote = 增速证据（如 "+250%"、搜索量区间）
- 词根循环：`profiles.<profile>.suggest_roots` 每个词根在 Trends 搜索一次，收 Rising 相关查询（P1 扩展，本轮可选）

## 7. Google suggest → trend

- 入口（L1b，已验证可用）：`curl -sx http://127.0.0.1:7890 "https://suggestqueries.google.com/complete/search?client=firefox&q=<url编码词根>"`，返回 JSON 数组 `[查询词,[联想词...],[],meta]`
- 对 `suggest_roots` 每词根一次调用；联想词里排除与词根完全相同的项，其余每个生成一条 trend 信号
- entity = 联想词全文；quote = 使用的词根；无 source_url（省略该字段）
- 注意：联想词池更新慢，重复词靠 finalize 脚本的 7 天窗口过滤，不要因为"眼熟"就跳过——交给脚本判
- 坑：不要用浏览器读这个接口——Chrome 会把 JSON 塞进 JSON 查看器的 shadow DOM，execute JS 读不到内容；curl+代理拿原始 JSON 才是正解

## 访问阶梯补充：L3 本机 Chrome 用法

```bash
osascript -e 'tell application "Google Chrome" to execute (active tab of front window) javascript "document.body.innerText.slice(0,5000)"'
```

- 前提：Chrome 已开"查看 > 开发者 > 允许 Apple 事件中的 JavaScript"；未开启则提示用户，不要静默降级伪造结果
- 用后台新建窗口（`make new window` + `set URL`）操作，绝不占用用户当前标签页；用完关闭自己开的窗口
- 适用于 Reddit（唯一可行通道）、Keyword Planner / Semrush 验证环节

## 本机网络实测（2026-09-13，勿凭想象覆盖）

| 目标 | WebFetch 直连 | curl+代理(7890) | 内置浏览器(L2) | 本机Chrome(L3) |
|---|---|---|---|---|
| github.com | ✅ | ✅ | — | — |
| hn.algolia.com | ✅ | ✅ | — | — |
| suggestqueries.google.com | ❌ 超时(被墙) | ✅ | ❌ 不走系统代理 | ✅ |
| reddit.com JSON API | ❌ | ❌ HTML拦截页 | — | — |
| old.reddit.com HTML | — | ❌ 302 | — | ✅ |
| toolify.ai | — | — | 待实测（直连可达站走 L2） | ✅ 备选 |

- 内置浏览器（IAB）不走系统代理：被墙域名在 L2 不可达，别浪费轮次，直接 L3
- Chrome 对 JSON 响应启用 JSON 查看器（shadow DOM），L3 的 execute JS 读不到原始 JSON——JSON 类数据一律 L1b curl+代理
- 系统代理端口用 `scutil --proxy` 查询，写死端口前先确认
