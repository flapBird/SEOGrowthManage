# Backlink Assistant Chrome Extension

SEO Growth Console 的本地浏览器执行端。Web 服务部署在云服务器，Extension 运行在用户自己的 Chrome 中；两者只通过 HTTPS JSON API 通信。插件相关源码、构建配置和接口文档均保存在本目录。

## 当前已实现（Phase 1 + Phase 2）

- Chrome Manifest V3 和 Side Panel。
- 云端服务器地址与 Extension Token 本地保存、连接测试。
- Web 控制台 `/extension` 创建/撤销 Token、创建 URL 任务、查看任务状态。
- 数据库仅保存 Token 哈希，明文只在创建后展示一次。
- 插件加载项目、原子领取下一任务、恢复当前任务和续租。
- 打开来源页面、标记 `prepared`、跳过并释放任务。
- 当前页面工作流、表单、登录状态、账号要求、登录阻断和 CAPTCHA 检测。
- “Submit a product / Launch your product”一类页面优先识别为 `directory`。
- 所有跨域 API 请求由 Background Service Worker 发出。
- 按服务器域名和当前页面域名请求可选权限。

页面分析仍然只检测 DOM，不填写表单、不点击提交、不绕过 CAPTCHA。Submission 和 Backlink Verification 将在后续阶段接入。

## 本地开发

```bash
cd extension
pnpm install
pnpm build
```

在 Chrome 中打开 `chrome://extensions`：

1. 开启 Developer mode。
2. 点击 Load unpacked。
3. 选择 `extension/dist`。
4. 后续重新构建后，在扩展页点击“重新加载”。
5. 点击插件图标打开 Side Panel。

开发监听构建：

```bash
pnpm dev
```

## 云端连接

部署更新后的 Web 服务并重启后：

1. 用原 Web 账号登录 SEO Growth Console。
2. 打开 `/extension`。
3. 创建 Extension Token，并立即复制明文。
4. 在同一页面为某个目标网站加入插件任务。
5. 在 Side Panel 填写云端 HTTPS 地址和 Token，保存并测试连接。
6. 刷新项目，选择项目并领取任务。

“登录状态”与“账号要求”是不同概念。已经登录 Product Hunt 时应显示“已登录 / 需要账号 / 登录阻断否”；缺少可靠证据时显示“未知”，不会再把“没看到登录框”等同于“无需账号”。

云端地址必须填写带可信证书的域名根地址，例如 `https://seo.example.com`。插件会拒绝公网 IP 和 `:8000`，避免 Extension Token 通过错误或不受信任的连接传输。

当前已经提供：

```text
GET   /api/v1/health
GET   /api/v1/projects
POST  /api/v1/tasks/next/claim
GET   /api/v1/tasks/:id
PATCH /api/v1/tasks/:id
```

请求使用：

```http
Authorization: Bearer <extension-token>
Content-Type: application/json
```

任务领取是原子操作，并带 20 分钟租约。同一 Token 重复领取会恢复其有效租约任务；插件重新打开时会同步任务并续租。

## 安全边界

- Token 不写入 manifest、源码或 Git。
- Token 只保存在 `chrome.storage.local`，不会发送到 Content Script 或目标网页。
- 云端数据库仅保存加盐哈希和短前缀，无法从数据库恢复明文。
- 云端服务地址必须使用 HTTPS；仅本地开发允许 localhost HTTP。
- Background 负责 API 通信；页面分析函数只返回结构化检测结果。
- Token 当前拥有插件 API 的全项目访问能力，建议每台浏览器单独创建并设置到期时间。
- 所有实际 Submit 动作仍必须由用户明确确认。
