# SEO Growth Console（SEO 增长工作台）

一个供个人站长长期部署使用的 SEO 工作台，包含外链发布管理和 itch.io 新游雷达。后端使用 FastAPI，页面使用 Jinja2 + htmx 服务端渲染，数据通过 SQLAlchemy ORM 持久化到 SQLite 文件，并内置可扩展的 APScheduler + Playwright 自动发布引擎。

## 模块划分

### 1. 登录鉴权

- `app/security.py` 负责管理员账号校验、服务端 session 建立/销毁和凭据加解密。
- 管理员用户名、密码、session 签名密钥全部来自环境变量。系统没有注册入口或多用户体系。
- `app/web.py` 的受保护路由统一挂载 `require_auth` 依赖。除登录页和登录页所需静态资源外，所有业务页面与接口都要通过 session 校验；未登录统一 303 跳转到 `/login`。
- session 记录持久化在 SQLite 的 `admin_sessions` 表中；浏览器 cookie 只保存随机不透明 token，数据库只保存加服务端 secret 后的 SHA-256 摘要。cookie 为 HttpOnly、SameSite=Lax，默认 7 天过期。生产 HTTPS 环境应设置 `COOKIE_SECURE=true`。

### 2. 基础数据管理

- `TargetSite`：自有目标网站，同时作为 Extension 的 Project Profile，保存名称、网址、作者、邮箱、Tagline、长短描述、关键词和备注。
- `Channel`：外链渠道，保存名称、网址、类型、状态、自动化能力和备注。
- 渠道类型固定为论坛、目录、博客评论、软文平台；状态为正常、失效、已被封禁。
- 目标网站和渠道都支持创建、搜索、编辑、删除。渠道列表支持按类型和状态组合筛选。
- 渠道页内置可批量导入、修改和删除的域名黑名单。每行可填写域名或完整 URL，系统统一规范化为根域；命中根域或其子域的渠道不能新增、修改、登记发布记录或执行自动发布。已有历史记录不会删除。
- 删除网站或渠道时，其关联发布记录、任务、日志或凭据会通过数据库外键级联删除，页面会先明确确认。

### 3. 发布记录与查询看板

- `Submission` 保存插件从预填、确认提交到审核结果的完整历史，`prepared` 只表示表单已填好；它与已经发布/验证的 `BacklinkRecord` 严格分开。
- `BacklinkVerification` 保存每次当前页面检查的 outcome、URL、anchor、rel 和时间。只有 outcome 为 `active` 才能创建正式 `BacklinkRecord`；后续发现链接消失会将正式记录标记为 `removed`。
- `BacklinkRecord` 关联一个 `TargetSite` 和一个 `Channel`，保存来源页、精确 Target URL、锚文本、rel、首次发现/最近验证时间、发布日期、发布方式和状态。
- 兼容发布方式仍为 `manual` / `auto`，状态为 `pending` / `live` / `removed`；新增证据来源 `manual / batch / automation / extension_verified`，用于区分人工登记、批量登记、适配器报告成功和插件实际验证。
- 新增或编辑记录时，目标网站或渠道变化会通过 htmx 请求 `/records/duplicate-check`。如果同一网站在同一渠道已有 `live` 记录，页面显示最近一条记录的发布日期，但不阻止提交。
- 登记发布记录时，目标网站和渠道下拉框上方提供名称/网址即时搜索；渠道选项只包含非黑名单渠道。
- `/records` 同时承担两个查询维度：指定目标网站可查看它已发布过的渠道；指定渠道可查看它服务过的目标网站。可按状态、兼容发布方式和证据来源筛选，并展示来源页、Target URL、rel、首次发现及最近验证时间。
- 自动任务生成的记录使用醒目的“自动引擎”标签。
- `SubmissionBatch` 和 `SubmissionBatchItem` 把“批量登记”与“未来提交计划”统一为一条工作流：选择一个渠道、多个目标网站、计划日期、统一查看地址、锚文本和备注，既可先保存为待提交计划，也可立即批量完成。
- 提交计划不会提前进入正式发布看板。批次详情支持只勾选本次实际完成的网站；系统为这些网站分别生成 `manual` 发布记录，未勾选的网站继续留在计划中，批次相应变为“部分完成”。全部处理后变为“已完成”。
- 同一批次适合个人主页、产品列表等一个页面容纳多个网站的渠道：所有生成记录共用一个查看地址，但仍按目标网站分别统计。批次删除不会删除已经生成的正式发布记录。
- Dashboard 展示按计划日期排序的待提交/部分完成批次；这是一项人工执行提醒，不会在日期到达时自动向渠道提交。

### 4. 渠道凭据存储

- `ChannelCredential` 与渠道一对一关联，保存用户名、加密密码和加密额外字段。
- `CredentialCipher` 使用 Fernet 对称加密；`FERNET_KEY` 只从环境变量读取，不写入源码或 SQLite。
- 页面不解密回显密码/API Key，只显示 `******`。更新时敏感输入留空会保留原密文。
- 旧版 `channels.login_username/login_password` 不再由 ORM、路由或页面使用。存量 SQLite 在首次启动新版时会将数据迁入 `ChannelCredential`，密码用当前 `FERNET_KEY` 加密成功后立即把旧明文列置空；已有加密凭据优先，不会被旧值覆盖。
- 自动适配器执行前才会在进程内解密，并以字典传给适配器；任务日志不会记录凭据。

### 5. 自动发布引擎

- `app/automation/base.py` 定义统一的 `ChannelAdapter.submit_link(target_url, anchor_text, credentials, config)` 异步接口和 `SubmissionResult`。
- `app/automation/registry.py` 是适配器注册表。以后增加渠道时，实现接口并在 `ADAPTERS` 中登记即可。
- `PlaywrightFormAdapter` 是一个可配置的表单型渠道参考实现，覆盖打开页面、可选登录、填写额外凭据字段、填写目标 URL/锚文本、提交、等待成功标志和提取实际发布 URL 的完整流程。
- `AutomationTask` 保存队列状态、重试次数、错误和最终 URL；`AutomationTaskLog` 保存每次执行日志。
- APScheduler 按配置间隔批量触发 `process_pending_tasks`。任务使用原子状态抢占，避免定时调度与手动执行造成重复提交。
- 只有状态为“正常”且勾选支持自动化的渠道能够创建、执行任务；执行前再次校验，失效/封禁渠道会转为“需人工介入”，不再自动尝试。
- 首次失败后最多自动重试 `AUTOMATION_MAX_RETRIES` 次（默认 3）。超过上限转为“需人工介入”，可在后台重置后再试。
- 只有适配器返回成功且给出实际发布 URL 时才会新增 `method=auto`、`origin=automation`、`status=live` 的记录；失败只写任务和日志。该来源表示“适配器报告成功”，不冒充 Extension 的独立 DOM Verification。

### 6. itch.io 新游雷达

- `app/itch_radar/` 与 `app/itch_web.py` 组成独立的 itch.io 新游发现模块，详见 [itch-radar.md](docs/itch-radar.md)。
- 每 5 分钟轮询 itch 官方 RSS（`/games/newest/free/html5/platform-web.xml`，即 browse 页加 `.xml`），通过游戏 URL 去重入库，记录 itch 精确上架时间与本地发现时间。
- 新游戏按轮限量补全详情页（作者、类型、标签、平台、截图、精确发布时间），请求间隔与 429 退避可配置；失败的记录留在「待补全」状态，下一轮自动重试。
- 轻质量门槛检查封面、简介长度、发布状态和 HTML5 平台标注，结果展示在页面上供人工取舍。
- 系统只负责发现和交付：每天在 `/itch` 页面导出当日 Markdown（含建议关键词），交给 AI 为 PlayBloo 生成独立页面，系统不做自动发布。

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
│   ├── itch_web.py             # itch.io 新游雷达页面（每日新游、导出 Markdown）
│   ├── itch_radar/
│   │   ├── parse.py            # RSS/详情页解析、关键词推导、质量门槛（纯函数）
│   │   └── fetcher.py          # RSS 轮询、详情补全、限速与退避、入库去重
│   ├── automation/
│   │   ├── base.py             # 适配器契约与提交结果
│   │   ├── registry.py         # 适配器注册表
│   │   ├── playwright_form.py  # Playwright 通用表单示例适配器
│   │   ├── engine.py           # 任务选择、执行、重试、日志和记录落库
│   │   └── scheduler.py        # APScheduler 周期调度
│   ├── templates/              # Jinja2 页面及 htmx 局部模板
│   └── static/                 # 页面样式与批量网站选择交互
├── data/                       # SQLite 持久化目录（Docker volume）
├── docs/                       # 文档目录
│   └── itch-radar.md           # itch.io 新游雷达说明
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

TargetSite ──< BacklinkTask >── Opportunity
     │              │                │
     └──────────────┴──< Submission >┘
                           │       │
                           │       └── BacklinkRecord（仅 active verification）
                           └──< BacklinkVerification
```

## Docker + Caddy HTTPS 部署

要求安装 Docker 与 Docker Compose。FastAPI 和 Caddy 分别运行在独立容器中：Caddy 自动管理 HTTPS 证书并反向代理到 Docker 内网的 Uvicorn。Uvicorn 固定为单 worker，避免每个 worker 各启动一个 APScheduler。

部署前需要准备一个域名或已有域名的子域名，并创建 A 记录指向服务器公网 IP。服务器安全组和系统防火墙需要开放 TCP 80、443；公网不再开放 8000。启动前还要确认 80/443 没有被宿主机上已有的 Nginx、Apache 或其他服务占用。

1. 创建配置：

   ```bash
   cp .env.example .env
   python3 -c "import secrets; print(secrets.token_urlsafe(48))"
   python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

   将第一条输出填入 `SESSION_SECRET`，第二条填入 `FERNET_KEY`，设置强密码 `ADMIN_PASSWORD`，并把 `APP_DOMAIN` 改为实际域名，例如 `seo.example.com`。不要在 `APP_DOMAIN` 中填写协议、路径或端口。`FERNET_KEY` 一旦用于入库就必须长期保管；丢失或变更后已有凭据无法恢复。

2. 启动：

   ```bash
   docker compose up -d --build
   ```

3. 等待 Caddy 完成首次证书申请，然后访问 `https://你的域名/login`。可用以下命令检查状态：

   ```bash
   docker compose ps
   docker compose logs caddy
   curl -I https://你的域名/login
   ```

4. Chrome Extension 的“服务器地址”填写同一个根地址，例如 `https://seo.example.com`，不要附加 `/extension`、`/api/v1` 或 `:8000`。

如果使用 Cloudflare 代理，首次部署排障时可先将 DNS 记录设为“仅 DNS”，确认 Caddy 已取得证书且域名可以直接访问后，再按需要启用代理。

SQLite 文件保存在宿主机 `./data/backlink_manager.db`，Caddy 证书保存在 Docker volume `caddy_data`。备份时建议先停止容器，再复制整个 `data/` 目录并单独保管 `.env`；不要把 `.env` 提交进 Git。

## itch.io 新游雷达快速使用

1. 首次使用登录后进入「ITCH 新游」，点击「立即抓取一轮」，系统抓取 itch 官方 RSS 并入库最近一批新游戏。
2. APScheduler 之后每 5 分钟自动轮询一次（可配置），新游戏自动入库并限量补全详情（作者、标签、平台、截图等）。
3. 每天打开 `/itch` 页面查看当天新游戏，可按日期回看、按状态筛选；质量提醒（缺封面、简介过短、未正式发布）只作参考，取舍由人工决定。
4. 点击「导出当日 Markdown」，把材料交给任意 AI 为 PlayBloo 生成独立游戏页面；做完回系统把该游戏标记为「已用于 PlayBloo」。
5. 出口被墙/限流的服务器需在 `.env` 配置 `ITCH_RADAR_PROXY`；详情页抓取速度参数不要调高，itch 会 429 限流。

详细的数据流、配置项和部署注意事项见 [itch-radar.md](docs/itch-radar.md)。

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
