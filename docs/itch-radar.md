# itch.io 新游雷达（/itch）

目标：PlayBloo 前三个月只做一件事——**第一时间收录 itch.io 最新可玩的浏览器游戏**。
本模块负责"发现 + 补全信息 + 每日交付材料"，PlayBloo 建页由人工拿着导出的
Markdown 交给任意 AI 完成，系统不做自动发布。

## 数据流

```
itch.io 官方 RSS（每 5 分钟轮询，仅 1 个请求）
   ↓  URL 去重入库（记录 itch 上架时间 / 发现时间）
详情页补全（每轮限量 10 款、间隔 4 秒、429 退避；失败留待下轮自动重试）
   ↓  作者 / 类型 / 标签 / 平台 / 截图 / 精确上架时间 / 质量门槛评估
/itch 页面（默认展示今天，可翻日期、按状态筛选）
   ↓  「导出当日 Markdown」
人工粘贴给 AI → PlayBloo 建页 → 回系统把该游戏标记为「已用于 PlayBloo」
```

数据源默认为 `https://itch.io/games/newest/free/html5/platform-web.xml`
（itch 官方 browse 页加 `.xml` 即 RSS，标题"Latest free HTML5 games for Web"，
每页 36 条）。5 分钟一轮意味着 itch 上架后约 5 分钟内进入系统；36 条的窗口
足够小时级轮询不漏游戏。

## 页面用法

- **立即抓取一轮**：手动触发一次"RSS 轮询 + 详情补全"，首次使用点它即可快速入库。
- **日期切换 / 状态筛选 / 搜索**：默认展示今天（东八区）上架的游戏。
- **质量提醒**：详情补全后会检查封面、简介长度、是否正式发布（Released）、
  平台是否标注 HTML5，不满足的卡片有黄色提示，是否采用由人工判断。
- **状态流转**：待补全(new) → 已就绪(ready) → 已用于 PlayBloo(used) / 已忽略(skipped)。
- **导出当日 Markdown**：生成一份可直接交给 AI 的材料（标题、URL、作者、
  上架时间、类型标签、简介、封面/截图、建议关键词、质量提醒），
  AI 据此为 PlayBloo 生成独立详情页。

## 配置项（环境变量 / .env）

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `ITCH_RADAR_ENABLED` | `true` | 总开关（关闭则不注册定时任务） |
| `ITCH_RADAR_POLL_INTERVAL_SECONDS` | `300` | RSS 轮询间隔（≥60） |
| `ITCH_RADAR_FEEDS` | newest/free/html5/platform-web.xml | 逗号分隔可配多个 feed，如再叠加 `/games/newest/free/platform-web.xml` |
| `ITCH_RADAR_DETAIL_BATCH` | `10` | 每轮最多补全多少款详情（0=只发现不补全） |
| `ITCH_RADAR_DETAIL_DELAY_SECONDS` | `4` | 详情页请求间隔（itch 会 429 限流，勿调太低） |
| `ITCH_RADAR_MAX_RETRIES` | `1` | 429 时的退避重试次数 |
| `ITCH_RADAR_PROXY` | 空 | 出口代理（如 `http://127.0.0.1:7890`）；留空跟随 HTTP(S)_PROXY 环境变量 |

## 部署注意

1. 新表 `itch_games` 由启动时的 `Base.metadata.create_all` 自动创建，无需手工迁移。
2. `requirements.txt` 新增 `beautifulsoup4`，需要 `docker compose build` 重建镜像。
3. 服务器必须能访问 `itch.io`（被墙/限流的网络需给容器配 `ITCH_RADAR_PROXY`）。
   itch 的限流特征：RSS 单请求高频轮询无风险；详情页批量抓取必须限速，
   遇到 429/522 系统会记录到 `last_error` 并在下一轮自动重试。
4. 长期统计口径：`itch_published_at`（itch 上架时刻）与 `discovered_at`
   （系统发现时刻）都在库里，可随时评估"从上架到入库"的延迟。

## 代码位置

- 解析与质量门槛：`app/itch_radar/parse.py`（纯函数，离线可测）
- 网络与入库：`app/itch_radar/fetcher.py`（`poll_feeds` / `enrich_pending` / `run_radar_cycle`）
- Web 路由：`app/itch_web.py`，模板 `app/templates/itch/list.html`
- 定时注册：`app/automation/scheduler.py`（job id `poll_itch_radar`）
- 测试：`tests/test_itch_radar.py`
