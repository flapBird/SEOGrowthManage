# 关键词发现功能彻底改造方案

> 依据：web.cafe 悬赏帖《你都在哪些网站挖掘需求？主要看这个网站的哪些地方？》
> （https://new.web.cafe/ask/bounty/0jch5yv6g7）——61 位从业者提名 166 个站点、
> 313 条"看哪里/怎么看"方法注解（讨论区评论为 0，方法全部来自选项附言）。
> 数据快照：`/tmp/webcafe_data/sites_clean.json`。

---

## 一、现状诊断：现有功能为什么不够

当前实现（`app/keyword_discovery/`）：

| 层 | 现状 | 问题 |
|---|---|---|
| 来源层 | 仅 `sitemap` / `trends_rss` / `manual` 三种 `KeywordSourceType`（models.py:131） | 只能盯"站长上新"。榜单类、社区类、评论类、付费验证类站点全部无法接入，而它们正是大家实际挖需求的主战场 |
| 清洗层 | `normalize_game_title` 硬编码游戏噪声词（normalizer.py） | 垂类锁死游戏，换赛道需重写 |
| 信号层 | SerpAPI 四路（autocomplete/trends/youtube/organic），默认 50 次/天 | 成本瓶颈；搜索信号是"代理指标"，且拿到的是时间差最晚的信息 |
| 评分层 | 热度35+新鲜25+意图20+竞争15+置信5 → HOT/HOLD/IGNORE | `source_count` 只计"被几个来源见过"，没有区分来源的信号类型和权重 |
| 复核层 | 远程 Claude Code Agent 队列（agent_queue.py） | 只用来"判断词"，能力浪费 |

一句话：**现在找的是"站长发布了什么"，而大家真正挖的是"用户在抱怨什么、钱正在流向哪里、什么正在突然变火"。**

## 二、从 166 个站点 + 313 条方法注解提炼的需求挖掘方法论

### 2.1 五类需求信号（按社区实际使用频率聚类）

| 信号类型 | 占比 | 典型站点（票数） | 大家看的"地方" |
|---|---|---|---|
| **A 新事物出现** | 23% | Toolify(38)、Product Hunt(25)、GitHub(12)、Hugging Face(10)、Hacker News(10)、There's An AI For That(15) | today/新上线页、月度/增长/收入榜、Trending、新模型发布 |
| **B 收入/付费验证** | 11% | TrustMRR(13)、Stripe 引荐流量榜(3)、AppSumo(3)、acquire/Flippa/microns、CodeCanyon | 收入榜单、真实 MRR、LTD 热销 |
| **C 流量/关键词反推** | 8% | Similarweb(20)、Semrush(15)、Ahrefs(5)、Traffic.cv(4)、Google Search Console | 关键词生成器、着陆页、New Keywords、Content Gap、大站内页词、vercel.app 等托管二级域名 |
| **D 痛点表达（抱怨/求助）** | 14% | Reddit(28)、App Store(8)、G2(6)、Chrome 插件商店(5)、alternativeto(4)、Quora(3)、Trustpilot/Capterra、Discord support 频道 | 1–3 星差评、Most Mentioned Cons、求助帖、求推荐帖、评论区"有没有工具能…" |
| **E 趋势与搜索行为** | ~20% | Google Trends(27)、Google 搜索联想/PAA(8)、X/Twitter(19)、Exploding Topics(4)、TikTok(5)、YouTube(4) | 飙升查询(Rising)、相关查询、词根库循环刷（哥飞 51 词根）、X 高互动推文反查域名年龄与流量 |

另外两类小众但高价值：**外包/招聘信号**（Upwork、Fiverr、boss直聘："企业花钱外包什么=付费意愿已验证"，4 条注解）与**技术栈情报**（BuiltWith、PublicWWW、Vercel/GitHub Pages 托管站：按 Stripe/Paddle/OpenAI API 筛出正在商业化的新站）。

### 2.2 时间差模型：信号越早越值钱

```
X/Reddit 先火 ──→ Trends 飙升 ──→ Similarweb/Semrush 可见 ──→ 竞争加剧
  (第0天，免费)      (第1-7天)        (滞后28天+)              (窗口关闭)
```

多位提交者明确表达了这个共识："很多新概念先在 X 上传播，等关键词工具显示明显搜索量时，竞争通常已经开始增加"。**改造后的系统核心目标就是尽量站在时间轴左侧。**

### 2.3 高频工作流（值得产品化的三个）

1. **词根 × Trends 循环**：维护需求词根库（online/generator/converter/"怎么"/"攻略"…）→ 在 Trends 飙升查询里刷词根 → 暴增的词再作为新词根追下去（可无限递归）。
2. **榜单黑马反查**：榜单（Toolify/PH/Similarweb）筛"上月不在榜、本月突然进榜"→ 分析核心功能/付费点/流量来源 → Trends + Google 联想验证 → 垂直化/本地化机会。
3. **差评→产品缺口→关键词**：竞品 1–3 星评论抽"太贵/太复杂/缺功能/要对接"→ 生成 `X alternative / X vs Y / X pricing / how to X without Y` 模板词 → 验证搜索量与竞争度。

## 三、改造方案

### 3.1 概念升级：Source → Collector → DemandSignal → Candidate

```
[Collector 采集器]──→[DemandSignal 需求信号抽取]──→[Candidate 候选词合成]──→[分层验证]──→[证据卡片]
   每类站点一个          从原始条目抽取              三路合成词          免费→贵       词+证据链
   (适配器注册表)        结构化信号                                       共振优先
```

### 3.2 采集器适配器框架（替代现在的 if-else 来源类型）

`KeywordSource` 增加一个 `collector` 字符串字段（替代枚举扩展的僵化），`fetch_source_entries` 改为注册表分发：

| Collector | 技术路线 | 覆盖站点 | 成本 |
|---|---|---|---|
| `http_xml`（现有） | httpx + sitemap/RSS 解析 | 大站 sitemap、Google Trends RSS | 免费 |
| `json_api` | 站点官方/半官方 JSON API | **Reddit**（`{sub}/search.json?q=…&sort=new`）、**GitHub**（Trending 页 HTML 也行、Search API：`created:>date stars:>n`）、**HN**（Algolia API）、**App Store 评论**（Apple 官方 RSS `itunes.apple.com/rss/customerreviews`）、**Google 联想**（suggest 接口） | 免费 |
| `html_select` | 配置化 CSS 选择器（config_json 里声明列表项/字段选择器），JS 重的配 Playwright | Toolify 榜单、SteamDB、Chrome 商店、Uneed、Traffic.cv | 免费 |
| `search_query` | 把"来源"参数化：词根库 × 平台查询 | Google Trends（Rising）、Semrush/Ahrefs API、PublicWWW | 免费~付费 |
| `manual`（现有） | 人工导入 | — | — |

关键点：**Reddit/GitHub/AppStore 评论/Google 联想全部免费且无需 JS 渲染**，P0 就能拿到三类高价值信号（新事物、痛点、搜索行为），不烧 SerpAPI。

### 3.3 需求信号抽取层（新增，改造的核心）

来源条目不再一律当"标题"处理，先抽取为结构化信号：

```python
class DemandSignal:            # 建议直接复用/扩展 KeywordSignalSnapshot
    signal_type: str           # new_product / complaint / request / alternative /
                               # revenue / hiring / trend / landing_page
    entity: str                # 抽取的实体：产品名/游戏名/工具名/词根
    quote: str                 # 原始引文（原帖、差评原文）
    source_url: str            # 证据链接
    emotion: str               # negative / asking / positive
    money_related: bool        # 是否涉及付费（价格抱怨、收入数据、外包预算）
```

抽取方式两档：
- **规则档**（免费）：标题/正则模板，如 Reddit 标题里含 "looking for|alternative to|is there a tool|how do I"、App Store 评论星级 ≤3；
- **LLM 档**（精准）：**复用现有 agent_queue 机制**——把原始帖子批次交给远程 Claude Code Agent 抽实体+判断信号类型，与现有"判断词"任务共用管线，Agent 从"评分裁判"升级为"信号抽取员+裁判"。

### 3.4 候选词三路合成

| 路径 | 输入 | 产出 |
|---|---|---|
| 直接词（现有逻辑保留） | new_product 信号实体（产品名/模型名/游戏名） | 名词新词：`sora2`、某新游戏名 |
| 痛点模板词（新增） | complaint/alternative 信号 | `竞品名 alternative`、`竞品名 vs X`、`how to 场景 without 竞品`、`竞品名 pricing` |
| 词根趋势词（新增） | 词根库 × Trends Rising 循环 | 暴增词及其衍生词，支持递归追踪 |

### 3.5 验证管线重排：本地权威工具优先，SerpApi 降级为兜底

现状每个候选固定烧 4 次 SerpAPI。全本地部署后，验证层直接用本机浏览器里已登录的权威工具：

1. **第 0 层（免费）**：Google suggest 联想 + 去重 + 语言过滤；
2. **第 1 层（免费）**：Trends 飙升确认（新增 `trend_velocity` 信号：7 天斜率）；
3. **第 2 层（本机登录工具，真实数据）**：Google Keyword Planner 读**真实搜索量区间**、Semrush 读 **KD / 相关词 / 竞品差距**——由 skill 在浏览器中查询并结构化记录；
4. **兜底**：SerpApi 仅在本机工具覆盖不到（如批量 YouTube 信号）时调用，额度池保留。

**共振分**取代现在的 `source_count`：
```
resonance = Σ (信号源独立数) × (信号类型权重)
权重参考：revenue 1.5 > complaint 1.3 > request 1.2 > new_product 1.0 > trend 0.8
（收入验证 > 真实抱怨 > 求助 > 新事物 > 单纯趋势）
```
HOT 判定增加条件：`resonance ≥ 阈值`（至少两类不同信号），避免单源噪音。

### 3.6 垂类 Profile 化（解锁游戏之外的赛道）

`normalize_game_title` → `normalize_title(raw, profile)`；profile 是配置（不写死在代码里）：
噪声词表、泛词表、词根库、字数/字母比规则、HOT 阈值、信号类型权重。
首批两个 profile：`games`（迁移现有规则）、`ai_tools`（按榜单注解里的习惯：tool/ai/bot/generator 噪声、model 词根）。

### 3.7 需求证据卡片（最大的产品体验差异）

候选详情页从"一个词 + 五维分数"升级为"词 + 证据链"：
> **wordforge.ai**
> 评分 78 · HOT
> 🔥 证据：Reddit r/SideProject 3 天前帖子"looking for cheaper alternative to X"（↑214）｜TrustMRR 收入榜 #23（$8.2k MRR）｜Trends 7 天 +340%｜Semrush 新词月搜 4.4k · KD 12
> → 每条证据都可点击回源。

实现：KeywordSignalSnapshot 本来就存 payload_json，把信号 quote/url 结构化后前端渲染即可，**无需新表**。

### 3.8 看板与通知

- 候选列表按信号类型分栏：新词雷达 / 痛点金矿 / 赚钱验证 / 外包信号；
- 通知（复用 notify 聚合推送）：摘要带上证据短句，如"Reddit 有人抱怨 X 太贵（原帖链接）→ 新候选 `x alternative`"。

## 四、分期落地

| 阶段 | 内容 | 涉及文件 |
|---|---|---|
| **P0（1–2 周）** | ① 本地运行现有 FastAPI 应用（localhost 工作台），停用云端关键词模块的调度；② 需求采集 skill v1：模型+真实 Chrome 每日过 Toolify today、Reddit、GitHub、App Store 评论、Google Trends Rising、Google suggest，产出统一 DemandSignal JSON 入库；③ 信号类型入 `KeywordSignalSnapshot.signal_type`；④ 共振分替换 source_count 计分 | 新增 skill 目录（站点清单+JSON 契约）、pipeline.py 入库适配 |
| **P1（3–4 周）** | ① skill 站点清单扩到 SteamDB、Chrome 商店、TrustMRR、X；② LLM 抽取层接 agent_queue；③ 痛点模板词生成；④ Keyword Planner / Semrush 浏览器验证环节接入 skill；⑤ 词根 × Trends 循环；⑥ 垂类 profile 配置化 | skill 清单、agent_queue.py、normalizer.py |
| **P2（按需）** | ① 需求证据卡片 UI 与分栏看板；② GSC 接入（自有站新曝光词）；③ Upwork/招聘类外包信号；④ SerpApi 兜底通道（YouTube 信号等本机工具覆盖不到的场景） | keyword_web.py、templates/keywords/ |

**边界**：本改造只动 `app/keyword_discovery/`、`keyword_web.py`、`models.py` 及关键词模板；`extension/` 外链发布插件一行不动。

## 五、第一批建议接入的站点（按性价比排序）

1. **Reddit**（28 票，免费 API，痛点+求助最密集）— 配 5–10 个垂直 subreddit；
2. **GitHub Trending/Search**（12 票，免费，新事物+Issues 功能请求）；
3. **App Store / Google Play 评论 RSS**（8 票，免费官方接口，竞品差评）；
4. **Toolify today + 收入榜**（38 票，真实浏览器直读，新站+变现验证）；
5. **Google Trends Rising × 词根库**（27 票，免费，趋势词）；
6. **Google suggest**（免费，搜索行为确认）；
7. **Hacker News Algolia**（10 票，免费，Ask/Show HN）；
8. **Chrome 商店差评**（5 票，真实浏览器直读，SaaS 缺口）；
9. **TrustMRR**（13 票，收入验证）；
10. **X 高互动链接反查**（19 票，可参考社区开源的 Twitter-Trend-Radar 思路）。

## 六、部署形态：关键词模块全部本地（Skill 化）

**结论**：关键词发现整体从云 Linux 服务器搬到本地 Mac，以"本地常驻工作台 + ZCode skill 采集"运行；云端只保留外链发布管理（浏览器插件必须轮询公网地址，这部分不动）。

**理由**：
1. 验证的黄金标准（Google Trends、Keyword Planner 真实搜索量、Semrush KD）都在本机浏览器的登录态里，云端拿不到；
2. 高价值来源（Toolify/SteamDB/X/Chrome 商店等）全部有 Cloudflare 或登录墙，云上数据中心 IP 基本抓不到——现有代码里"空结果疑似被拦截"的防御逻辑就是这个问题留下的伤疤；真实 Chrome + 住宅 IP + 真实登录态一次通过；
3. 需求发现是**天级时效**（X 先火 → Trends 隔天起 → Semrush 滞后 28 天+），不需要 7×24 在线，每天 1–2 轮足够；
4. 页面改版时模型现场适应，不会像云上定时爬虫那样静默失败。

**运行形态**：
```
本地 Mac
  ├─ FastAPI 工作台（现有代码原样跑，localhost 访问；SQLite 数据库本地持久化）
  │    └─ 指纹去重 / 基线 / 评分状态机 / 通知通道 全部复用
  ├─ ZCode 定时自动化（每天早上触发；错过可手动补跑"跑一轮需求采集"）
  │    └─ skill：按站点清单用真实 Chrome 逐站采集 → 统一 DemandSignal JSON
  │       → 走现有 ingest 入库 → 去重/评分/状态流转自动完成 → 生成当日报告
  └─ 验证：skill 在浏览器中查 Keyword Planner / Semrush / Trends 并结构化记录

云端服务器（保留现状）
  └─ 外链发布管理 + 插件 API（/api/v1 不动）；关键词模块调度停用
```

**风险与对策**：
| 风险 | 对策 |
|---|---|
| Mac 关机时定时任务不执行 | 天级时效下影响可忽略；醒来自动补跑一轮即可 |
| 每轮模型 token 成本 | 单轮 10–15 分钟量级；JSON 契约固定，模型只负责"看页面→出结构" |
| skill 单轮失败 | 指纹去重保证幂等，重跑不产生重复数据 |
| Semrush / Google Ads 账号风控 | 控制每轮查询量级（词根循环不刷上百次），保持人工使用节奏 |
| 本地 SQLite 数据安全 | data 目录定期备份（rsync/iCloud），与云端外链数据隔离 |
