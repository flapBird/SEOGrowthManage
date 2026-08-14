# SEO Growth Console（SEO 增长工作台）

一个供个人站长长期部署使用的 SEO 工作台，包含外链发布管理和关键词机会发现。后端使用 FastAPI，页面使用 Jinja2 + htmx 服务端渲染，数据通过 SQLAlchemy ORM 持久化到 SQLite 文件，并内置可扩展的 APScheduler + Playwright 自动发布引擎。

## 模块划分

### 1. 登录鉴权

- `app/security.py` 负责管理员账号校验、服务端 session 建立/销毁和凭据加解密。
- 管理员用户名、密码、session 签名密钥全部来自环境变量。系统没有注册入口或多用户体系。
- `app/web.py` 的受保护路由统一挂载 `require_auth` 依赖。除登录页和登录页所需静态资源外，所有业务页面与接口都要通过 session 校验；未登录统一 303 跳转到 `/login`。
- session 记录持久化在 SQLite 的 `admin_sessions` 表中；浏览器 cookie 只保存随机不透明 token，数据库只保存加服务端 secret 后的 SHA-256 摘要。cookie 为 HttpOnly、SameSite=Lax，默认 7 天过期。生产 HTTPS 环境应设置 `COOKIE_SECURE=true`。

### 2. 基础数据管理

- `TargetSite`：自有目标网站，保存名称、网址、备注。
- `Channel`：外链渠道，保存名称、网址、类型、状态、自动化能力和备注。
- 渠道类型固定为论坛、目录、博客评论、软文平台；状态为正常、失效、已被封禁。
- 目标网站和渠道都支持创建、搜索、编辑、删除。渠道列表支持按类型和状态组合筛选。
- 渠道页内置可批量导入、修改和删除的域名黑名单。每行可填写域名或完整 URL，系统统一规范化为根域；命中根域或其子域的渠道不能新增、修改、登记发布记录或执行自动发布。已有历史记录不会删除。
- 删除网站或渠道时，其关联发布记录、任务、日志或凭据会通过数据库外键级联删除，页面会先明确确认。

### 3. 发布记录与查询看板

- `BacklinkRecord` 关联一个 `TargetSite` 和一个 `Channel`，保存实际发布 URL、锚文本、发布日期、发布方式和状态。
- 发布方式为 `manual` / `auto`，状态为 `pending` / `live` / `removed`。
- 新增或编辑记录时，目标网站或渠道变化会通过 htmx 请求 `/records/duplicate-check`。如果同一网站在同一渠道已有 `live` 记录，页面显示最近一条记录的发布日期，但不阻止提交。
- 登记发布记录时，目标网站和渠道下拉框上方提供名称/网址即时搜索；渠道选项只包含非黑名单渠道。
- `/records` 同时承担两个查询维度：指定目标网站可查看它已发布过的渠道；指定渠道可查看它服务过的目标网站。两者均可继续按状态和发布方式筛选，并默认按发布日期倒序。
- 自动任务生成的记录使用醒目的“自动引擎”标签。
- `SubmissionBatch` 和 `SubmissionBatchItem` 把“批量登记”与“未来提交计划”统一为一条工作流：选择一个渠道、多个目标网站、计划日期、统一查看地址、锚文本和备注，既可先保存为待提交计划，也可立即批量完成。
- 提交计划不会提前进入正式发布看板。批次详情支持只勾选本次实际完成的网站；系统为这些网站分别生成 `manual` 发布记录，未勾选的网站继续留在计划中，批次相应变为“部分完成”。全部处理后变为“已完成”。
- 同一批次适合个人主页、产品列表等一个页面容纳多个网站的渠道：所有生成记录共用一个查看地址，但仍按目标网站分别统计。批次删除不会删除已经生成的正式发布记录。
- Dashboard 展示按计划日期排序的待提交/部分完成批次；这是一项人工执行提醒，不会在日期到达时自动向渠道提交。

### 4. 渠道凭据存储

- `ChannelCredential` 与渠道一对一关联，保存用户名、加密密码和加密额外字段。
- `CredentialCipher` 使用 Fernet 对称加密；`FERNET_KEY` 只从环境变量读取，不写入源码或 SQLite。
- 页面不解密回显密码/API Key，只显示 `******`。更新时敏感输入留空会保留原密文。
- 自动适配器执行前才会在进程内解密，并以字典传给适配器；任务日志不会记录凭据。

### 5. 自动发布引擎

- `app/automation/base.py` 定义统一的 `ChannelAdapter.submit_link(target_url, anchor_text, credentials, config)` 异步接口和 `SubmissionResult`。
- `app/automation/registry.py` 是适配器注册表。以后增加渠道时，实现接口并在 `ADAPTERS` 中登记即可。
- `PlaywrightFormAdapter` 是一个可配置的表单型渠道参考实现，覆盖打开页面、可选登录、填写额外凭据字段、填写目标 URL/锚文本、提交、等待成功标志和提取实际发布 URL 的完整流程。
- `AutomationTask` 保存队列状态、重试次数、错误和最终 URL；`AutomationTaskLog` 保存每次执行日志。
- APScheduler 按配置间隔批量触发 `process_pending_tasks`。任务使用原子状态抢占，避免定时调度与手动执行造成重复提交。
- 只有状态为“正常”且勾选支持自动化的渠道能够创建、执行任务；执行前再次校验，失效/封禁渠道会转为“需人工介入”，不再自动尝试。
- 首次失败后最多自动重试 `AUTOMATION_MAX_RETRIES` 次（默认 3）。超过上限转为“需人工介入”，可在后台重置后再试。
- 只有适配器返回成功且给出实际发布 URL 时才会新增 `method=auto`、`status=live` 的正式发布记录；失败只写任务和日志。

### 6. 关键词发现与复查

- `app/keyword_discovery/` 是与外链发布解耦的独立流水线，共享管理员鉴权、SQLite、Fernet 和 APScheduler。
- 来源支持标准 Sitemap、Sitemap Index（递归展开两层）、gzip Sitemap、RSS 及人工逐行导入。下载带指数退避重试，子 sitemap 并发抓取（受并发数与请求间隔限流），默认用浏览器 UA 以绕过 WAF 对脚本 UA 的误伤。每个来源必须确认条款或授权允许自动访问，并尊重对方的 Crawl-delay。
- `KeywordSourceItem` 保存不可变来源条目并通过指纹比较发现新增；`KeywordCandidate` 保存标准化、去重后的候选；`KeywordSignalSnapshot` 保存每次搜索信号快照。抓取返回空结果时不更新基线，避免误判全量”新增”。
- 清洗会去掉 gameplay、walkthrough、长数字 ID 等噪声，但保留原始标题和 URL 便于追溯。
- 每个候选按 Google Autocomplete、Google Trends、YouTube 搜索和 Google 竞争结果四类 SerpAPI 信号评分。YouTube 快照重复采集后会计算近似播放增速。
- 状态分为 `HOT`、`HOLD`、`IGNORE` 和待分析；HOLD 按分数在 24 小时、72 小时或 7 天后复查，IGNORE 冷却 30 天后可重新激活。
- `SerpApiPool` 支持多个合法持有的 API Key，Key 使用 Fernet 加密。系统通过免费 Account API 同步余额，按优先级、剩余额度和最近使用时间选池，遇到 429 自动切换。
- `KEYWORD_SERPAPI_DAILY_BUDGET` 是应用自己的每日安全预算，默认 50 次；一个候选完整分析约使用 4 次查询，因此默认每天最多自动完整分析约 12 个候选。
- **远程 Agent 智能判断**：可选的远程 AI 驱动二次筛选，通过本地启发式过滤减少 API 成本，批量送至 Claude Code Agent 做综合判断，支持 HOT/COLD 分类和 KD 预估，详见 [agent-integration.md](docs/agent-integration.md)。
- 通知能力：`NotifyChannel` 支持 Server酱微信、企业微信群机器人和 SMTP 邮件三种通道，配置用 Fernet 加密入库，页面不回显明文。每轮抓取结束后聚合一条新增摘要（包含关键字词样）；当某来源新增占比超过 `KEYWORD_ANOMALY_RATIO`（默认 0.3）或抓取失败时附带异常告警；候选在分析中新晋 HOT 或经 Agent 判定为 HOT 时也会聚合推送。

## 核心目录与职责

```text
./
├── app/
│   ├── main.py                 # FastAPI 生命周期、中间件、路由装配
│   ├── config.py               # 环境变量配置及启动校验
│   ├── database.py             # SQLAlchemy engine/session、SQLite 外键
│   ├── models.py               # 业务模型、服务端 session 模型和枚举
│   ├── security.py             # 管理员 session 与 Fernet 加解密
│   ├── web.py                  # 页面、表单、CRUD、筛选和 htmx 端点
│   ├── automation/
│   │   ├── base.py             # 适配器契约与提交结果
│   │   ├── registry.py         # 适配器注册表
│   │   ├── playwright_form.py  # Playwright 通用表单示例适配器
│   │   ├── engine.py           # 任务选择、执行、重试、日志和记录落库
│   │   └── scheduler.py        # APScheduler 周期调度
│   ├── keyword_discovery/
│   │   ├── normalizer.py       # 游戏名清洗、语言和泛词过滤
│   │   ├── sources.py          # Sitemap/RSS 下载（重试退避、并发、递归 index）和安全解析
│   │   ├── serpapi.py          # 加密多额度池、余额同步和故障切换
│   │   ├── pipeline.py         # 历史比对、信号聚合、评分、自动复查和通知触发
│   │   ├── notify.py           # 通知通道分发（Server酱 / 企业微信 / 邮件）
│   │   ├── agent_filter.py     # 本地启发式过滤，剔除不值得送 Agent 的候选
│   │   ├── agent_queue.py      # 文件队列管理，批量送出和回收 Agent 判断结果
│   │   └── keyword_web.py      # 候选、来源、日志、额度池和通知通道页面
│   ├── templates/              # Jinja2 页面及 htmx 局部模板
│   │   └── agent/              # Agent 管理页面模板
│   └── static/                 # 页面样式与批量网站选择交互
│       └── agent.css           # Agent 管理界面样式
├── data/                       # SQLite 持久化目录（Docker volume）
├── docs/                       # 文档目录
│   └── agent-integration.md    # 远程 Agent 集成指南
├── tests/                      # 鉴权、CRUD、加密、查询及任务状态机测试
├── Dockerfile
└── docker-compose.yml
```

核心关系如下：

```text
TargetSite ──< BacklinkRecord >────────── Channel ── ChannelCredential
     │              ▲                       │
     │              │                       ├──< SubmissionBatch ──< SubmissionBatchItem
     │              └── completed item ─────┘                         │
     │                                                               └── TargetSite
     └──────< AutomationTask >──────── Channel
                    │
                    └──< AutomationTaskLog
```

## Docker 部署

要求安装 Docker 与 Docker Compose。项目使用包含 Chromium 的官方 Playwright Python 基础镜像，并固定 Uvicorn 为单 worker；这是为了避免每个 worker 各启动一个 APScheduler。

1. 创建配置：

   ```bash
   cp .env.example .env
   python3 -c "import secrets; print(secrets.token_urlsafe(48))"
   python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

   将第一条输出填入 `SESSION_SECRET`，第二条填入 `FERNET_KEY`，并设置强密码 `ADMIN_PASSWORD`。`FERNET_KEY` 一旦用于入库就必须长期保管；丢失或变更后已有凭据无法恢复。

2. 启动：

   ```bash
   docker compose up -d --build
   ```

3. 访问 `http://服务器IP:8000/login`。生产环境建议用 Caddy/Nginx 配置 HTTPS 反向代理，并把 `.env` 中 `COOKIE_SECURE` 改为 `true`。

SQLite 文件保存在宿主机 `./data/backlink_manager.db`。备份时建议先停止容器，再复制整个 `data/` 目录和单独保管 `.env`；不要把 `.env` 提交进 Git。

## 关键词发现快速使用

1. 进入“关键词发现”→“SerpAPI 额度池”，添加一个或多个本人/团队合法持有的 API Key，再点击“同步全部额度”。页面只展示余额，永不回显明文 Key。
2. 进入“通知设置”，按需添加 Server酱微信、企业微信群机器人或 SMTP 邮件通道，配置字段用 Fernet 加密入库，页面只显示 `******`。点“测试推送”验证配置是否通畅。
3. 进入“来源与日志”，添加条款允许自动访问的 Sitemap 或 Google Trends RSS，选择语言、国家和抓取间隔。Sitemap 只用于发现新增 URL，不被当作排行榜热度。来源的高级 JSON 配置可覆盖默认抓取参数，例如 `{"max_child_sitemaps": 100, "max_concurrency": 10, "request_delay_seconds": 0.3, "user_agent": "自定义 UA"}`。
4. 对无法自动抓取的平台，可把你人工查看到的榜单游戏名复制到“人工导入候选”，每行一个。
5. APScheduler 会定期比较来源历史并生成去重候选。待分析候选按照每日额度预算查询 Autocomplete、Trends、YouTube 和 Google SERP。每轮抓取的新增摘要、异常告警（新增占比超过阈值或抓取失败）和新晋 HOT 候选会聚合推送到已配置的通知通道。
6. 在候选列表查看 HOT/HOLD/IGNORE；进入详情可看分项分数、信号时间线、立即重新分析或人工调整判断。

只要服务器和 SerpAPI 可用额度已经持有，这一模块通常不产生新增现金支出。它不是无限免费：超出 SerpAPI 额度、购买额外额度、增加服务器/代理或使用其他付费数据源仍会产生费用。应用不会自动购买额度，达到内部每日预算或所有池耗尽后会停止查询并等待额度恢复。

## 本地开发与测试

要求 Python 3.11+：

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
cp .env.example .env
# 修改 .env；本地 DATABASE_URL 可用 sqlite:///./data/backlink_manager.db
.venv/bin/playwright install chromium
.venv/bin/uvicorn app.main:app --reload
```

运行测试：

```bash
.venv/bin/python -m pytest
```

## 从录入渠道到自动发布：完整示例

以下示例假设有一个简单目录站，其发布页包含目标 URL、锚文本和提交按钮，发布成功后页面上出现结果链接。

### 第一步：录入目标网站和新渠道

1. 登录后进入“目标网站”→“新增网站”，录入：
   - 名称：`我的产品站`
   - 网址：`https://my-product.example`
2. 进入“外链渠道”→“新增渠道”，录入：
   - 名称：`示例目录站`
   - 网址：`https://directory.example`
   - 类型：`目录`
   - 状态：`正常`
   - 勾选“支持自动化提交”
   - 适配器选择：`Playwright 通用表单示例`
3. 在适配器 JSON 配置中填入：

   ```json
   {
     "form_url": "https://directory.example/login",
     "username_selector": "#username",
     "password_selector": "#password",
     "login_submit_selector": "button[type=submit]",
     "post_login_url": "https://directory.example/submit",
     "target_url_selector": "#target_url",
     "anchor_text_selector": "#anchor_text",
     "submit_selector": "button.publish",
     "success_selector": ".publish-success",
     "result_url_selector": ".publish-success a",
     "timeout_ms": 30000
   }
   ```

   无需登录的表单可以省略 `username_selector`、`password_selector`、`login_submit_selector`、`post_login_url`。如果表单还要 API Key，可配置：

   ```json
   {
     "credential_field_selectors": {
       "api_key": "#api_key"
     }
   }
   ```

   该字段应与上面的完整 JSON 合并，不能把两个 JSON 分开保存。`result_url_selector` 应指向成功页上的链接；若省略，适配器使用提交后的当前页面 URL。

### 第二步：手动登记一条记录

进入“发布记录”→“登记发布记录”，选择“我的产品站”和“示例目录站”，填写实际 URL、锚文本、发布日期，方式选 `manual`，状态选 `live` 后保存。

以后再次选择同一网站与渠道时，htmx 会立即提示已有 `live` 记录及其发布日期。提示不阻止保存，确需同渠道多发一条时可以继续。

如果一个渠道能够在同一个个人主页或产品列表中放置多个网站，可以改用批量流程：

1. 打开渠道详情，点击“批量提交 / 安排计划”。
2. 搜索并勾选本批次涉及的多个目标网站；已有正常记录的网站会显示最近发布日期，但仍允许选择。
3. 填写计划日期、批次名称、统一查看地址和备注。尚未提交时点击“保存为提交计划”；已经完成时点击“立即登记完成”。
4. 对计划批次，可在 Dashboard 或“提交计划”中进入详情，勾选本次实际完成的网站并填写查看地址。系统只为勾选的网站生成正式记录，其余网站继续等待下一次处理。
5. 当全部网站完成或取消剩余计划后，批次自动结束。删除批次只清理计划组织信息，不会删除已生成的发布记录。

### 第三步：配置渠道登录凭据

进入“外链渠道”并打开“示例目录站”详情，在“登录凭据”中填写用户名、密码和可选 API Key，点击“加密保存凭据”。保存后页面只出现 `******`，SQLite 中保存的是 Fernet 密文。

### 第四步：触发自动发布任务

1. 进入“自动任务”→“新建任务”。
2. 选择“我的产品站”和“示例目录站”，填写锚文本，重试次数保留默认 3，加入队列。
3. 等待 APScheduler 下一轮处理，或进入任务详情点击“立即执行”。
4. 引擎解密凭据并调用 `PlaywrightFormAdapter`：登录目录站 → 打开提交页 → 填目标 URL 和锚文本 → 提交 → 等待成功标志 → 提取实际发布 URL。
5. 成功后任务变为“成功”，系统自动生成一条 `auto + live` 发布记录；在查询看板中会显示蓝色“自动引擎”标签。
6. 若失败，详情页会显示错误与每次尝试日志。默认进行 3 次自动重试，仍失败则进入“需人工介入”；修正渠道配置或凭据后点击“重置重试”。失败过程不会产生正式发布记录。

## 扩展真实渠道适配器

新建一个继承 `ChannelAdapter` 的类，实现 `submit_link`，返回 `SubmissionResult`。然后在 `app/automation/registry.py` 的 `ADAPTERS` 注册新的 `adapter_key`，并在渠道表单的适配器下拉框增加选项。适配器应遵循三个原则：

1. 不在日志中输出密码、Cookie、API Key 或完整页面源码。
2. 只有确认渠道真正接受提交后才返回 `success=True`，并尽量返回可公开访问的实际发布 URL。
3. 对可重试的网络/页面错误返回失败，让统一任务引擎负责重试；不要自行写入 `BacklinkRecord`。
