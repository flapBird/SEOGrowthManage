# itch.io 新游雷达（/itch）

目标：PlayBloo 前三个月只做一件事——**第一时间收录 itch.io 最新可玩的浏览器游戏**。
本模块负责"发现 + 补全信息 + 每日交付材料"，PlayBloo 建页由人工拿着导出的
Markdown 交给任意 AI 完成，系统不做自动发布。

## 数据流

```
itch.io「New & Popular」官方 RSS（每 5 分钟轮询，仅 1 个请求）
   ↓  每日配额（默认 10 款/天，按榜单顺序优先收录排名靠前的）
   ↓  URL 去重入库（前面日子抓到过的不再收录，也不占当日配额）
详情页补全（每轮限量 10 款、间隔 4 秒、429 退避；失败留待下轮自动重试）
   ↓  作者 / 类型 / 标签 / 平台 / 截图 / 精确上架时间 / 质量门槛评估
/itch 页面（默认展示今天，可翻日期、按状态筛选）
   ↓  「导出当日 Markdown」
人工粘贴给 AI → PlayBloo 建页 → 回系统把该游戏标记为「已用于 PlayBloo」
```

数据源默认为 `https://itch.io/games/new-and-popular/free/platform-web.xml`
（itch「New & Popular」榜单，免费网页游戏）。早期版本用的
`/games/newest/free/html5/platform-web.xml`（newest 全量）每天真实上新 300+ 款，
无法人工消化，已替换为精选榜单 + 每日配额的模式；想换回全量或叠加其他源，
改 `ITCH_RADAR_FEEDS`（逗号分隔）即可。

## 页面用法

- **立即抓取一轮**：手动触发一次"RSS 轮询 + 详情补全"，首次使用点它即可按当日配额快速收录榜单前 10 款。
- **日期切换 / 状态筛选 / 搜索**：默认展示今天（东八区）上架的游戏。
- **质量提醒**：详情补全后会检查封面、简介长度、是否正式发布（Released）、
  平台是否标注 HTML5，不满足的卡片有黄色提示，是否采用由人工判断。
- **状态流转**：待补全(new) → 已就绪(ready) → 已用于 PlayBloo(used) / 已忽略(skipped)。
- **批量标记已用**：卡片右上角有勾选框，汇总栏可「全选本页」，一键把勾选的游戏全部标记为已用；
  做完一批页面后勾选对应游戏即可，不用逐个点。

## 外部 skill / 聚合站对接接口

两个 HTTP 接口，让"添加游戏的 skill"或 PlayBloo 后端全自动对接，无需人工在页面上操作：

- 先在服务器 `.env` 配置 `ITCH_RADAR_API_KEY=<自定义密钥>`（留空 = 接口关闭）。
- 鉴权：请求头 `X-API-Key: <密钥>`（也支持 `Authorization: Bearer <密钥>`）；
  密钥错误 401，服务端未配置密钥 403。

### 1. 拉取游戏清单：`GET /api/itch/games`

```bash
curl "https://你的域名/api/itch/games?date=2026-10-11&status=ready" \
     -H "X-API-Key: <ITCH_RADAR_API_KEY>"
```

- 参数：`date`（收录日，缺省今天/东八区）、`status`（`new`/`ready`/`used`/`skipped`，
  缺省全部）、`limit`（默认 300，上限 300）。
- 返回：`{"date": "...", "count": n, "games": [...]}`，每个游戏含
  `url / title / author / cover_url / description / price / status / genres / tags /
  platforms / screenshots / keywords / quality_ok / quality_notes / itch_published_at`。
- 字段和页面导出的 Markdown 一致，skill 拿到即可直接生成 PlayBloo 页面。

### 2. 回写标记：`POST /api/itch/mark-used`

```bash
curl -X POST https://你的域名/api/itch/mark-used \
     -H "X-API-Key: <ITCH_RADAR_API_KEY>" \
     -H "Content-Type: application/json" \
     -d '{"urls": ["https://x.itch.io/a", "https://y.itch.io/b"]}'
```

- 请求体三种模式（JSON）：
  - `{"date": "YYYY-MM-DD"}` —— 标记某一天收录的全部游戏；
  - `{"date": "YYYY-MM-DD", "urls": [...]}` —— 只标记当天里指定的游戏；
  - `{"urls": [...]}` —— 按 URL 标记（自动归一化，带 query/尾斜杠都能匹配）。
- 返回 `{"marked": <新标记数量>, "not_found": [...]}`（not_found 仅在传 urls 时返回，
  列出库里没有的 URL）；已是"已用"状态的游戏不会重复计数。

### skill 的典型全自动流程

```
GET /api/itch/games?status=ready        # 拉当天可做的游戏（含关键词、质量结论）
   ↓  skill 挑选游戏 → 生成 PlayBloo 详情页
POST /api/itch/mark-used {"urls": [...]}  # 把刚建完页的游戏批量标记为已用
```

标记后页面上这些游戏显示"已用于 PlayBloo"，配合每日 10 款的配额，
`status` 筛选能精确看出"今天还剩几个没做"。
- **导出当日 Markdown**：生成一份可直接交给 AI 的材料（标题、URL、作者、
  上架时间、类型标签、简介、封面/截图、建议关键词、质量提醒），
  AI 据此为 PlayBloo 生成独立详情页。

## 配置项（环境变量 / .env）

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `ITCH_RADAR_ENABLED` | `true` | 总开关（关闭则不注册定时任务） |
| `ITCH_RADAR_POLL_INTERVAL_SECONDS` | `300` | RSS 轮询间隔（≥60） |
| `ITCH_RADAR_FEEDS` | new-and-popular/free/platform-web.xml | 逗号分隔可配多个 feed |
| `ITCH_RADAR_DAILY_LIMIT` | `10` | 每天最多新收录多少款（按榜单顺序收录；0 = 不限量）；当天已达上限时轮询直接跳过，往日已收录的游戏重复出现不占额度 |
| `ITCH_RADAR_DETAIL_BATCH` | `10` | 每轮最多补全多少款详情（0=只发现不补全） |
| `ITCH_RADAR_DETAIL_DELAY_SECONDS` | `4` | 详情页请求间隔（itch 会 429 限流，勿调太低） |
| `ITCH_RADAR_MAX_RETRIES` | `1` | 429 时的退避重试次数 |
| `ITCH_RADAR_PROXY` | 空 | 出口代理（如 `http://127.0.0.1:7890`）；留空跟随 HTTP(S)_PROXY 环境变量 |
| `ITCH_RADAR_API_KEY` | 空 | 聚合站回写接口 `POST /api/itch/mark-used` 的密钥；留空 = 接口关闭 |

## 部署注意

1. 新表 `itch_games` 由启动时的 `Base.metadata.create_all` 自动创建，无需手工迁移。
2. `requirements.txt` 新增 `beautifulsoup4`，需要 `docker compose build` 重建镜像。
3. 服务器必须能访问 `itch.io`。两类典型故障：
   - **429/522（限流/瞬时不可达）**：RSS 单请求高频轮询无风险；详情页批量抓取必须限速。
   - **403（IP 被防护拦截）**：itch 的 Cloudflare 防护常对数据中心 IP 的游戏详情页请求
   返回 403，RSS 一般不受影响。系统已带 Referer/Sec-Fetch 浏览器式请求头，并把失败
   按指数退避重试（2h→4h→…→封顶 24h，8 次后仅手动触发）；根治办法是给容器配置
   `ITCH_RADAR_PROXY` 走住宅/干净的代理出口。被拦截的游戏基础信息（标题、封面、简介、
   上架时间）来自 RSS，仍然可用、可导出。
4. 长期统计口径：`itch_published_at`（itch 上架时刻）与 `discovered_at`
   （系统发现时刻）都在库里，可随时评估"从上架到入库"的延迟。

## 代码位置

- 解析与质量门槛：`app/itch_radar/parse.py`（纯函数，离线可测）
- 网络与入库：`app/itch_radar/fetcher.py`（`poll_feeds` / `enrich_pending` / `run_radar_cycle`）
- Web 路由：`app/itch_web.py`，模板 `app/templates/itch/list.html`
- 定时注册：`app/automation/scheduler.py`（job id `poll_itch_radar`）
- 测试：`tests/test_itch_radar.py`
