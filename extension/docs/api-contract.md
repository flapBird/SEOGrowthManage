# Extension API Contract

服务端使用 `/api/v1` 前缀。除 Token 创建页面外，插件 API 只接受：

```http
Authorization: Bearer <extension-token>
Content-Type: application/json
```

## Health

```http
GET /api/v1/health
```

```json
{"status":"ok","service":"seo-growth-console","apiVersion":"v1"}
```

## Projects

```http
GET /api/v1/projects
```

```json
[
  {
    "id": 1,
    "name": "Example Project",
    "website": "https://example.com",
    "authorName": "Alice",
    "email": "alice@example.com",
    "tagline": "Example tagline",
    "shortDescription": "Short description",
    "mediumDescription": "Medium description",
    "longDescription": "Long description",
    "keywords": ["seo", "growth"]
  }
]
```

`Project` 直接复用 Web 端已有的 `TargetSite`，不维护第二套项目表。

## Claim next task

```http
POST /api/v1/tasks/next/claim
Idempotency-Key: <uuid>

{"projectId": 1}
```

成功响应：

```json
{
  "id": 10,
  "projectId": 1,
  "opportunityId": 20,
  "workflow": "directory",
  "status": "processing",
  "sourceUrl": "https://publisher.example/submit",
  "sourceDomain": "publisher.example",
  "targetUrl": "https://example.com/product",
  "anchorText": "Example",
  "note": null,
  "leaseExpiresAt": "2026-09-01T10:20:00",
  "createdAt": "2026-09-01T10:00:00",
  "updatedAt": "2026-09-01T10:00:00",
  "project": {
    "id": 1,
    "name": "Example Project",
    "website": "https://example.com",
    "authorName": "Alice",
    "email": "alice@example.com",
    "tagline": "Example tagline",
    "shortDescription": "Short description",
    "mediumDescription": "Medium description",
    "longDescription": "Long description",
    "keywords": ["seo", "growth"]
  }
}
```

领取会将 `ready` 或租约过期的 `processing` 任务原子转换为 `processing`，租约为 20 分钟。同一 Token 在同一项目重复领取时恢复现有有效任务。无任务返回 `404`。

## Create task by source URL

```http
POST /api/v1/tasks
```

```json
{
  "projectId": 1,
  "sourceUrl": "https://www.toolify.ai/submit",
  "workflow": "directory",
  "targetUrl": "https://example.com/product",
  "anchorText": "Example",
  "note": "backlink-submit skill"
}
```

与排队领取不同，此接口为"明确知道要提交哪个页面"的调用方（外链提交技能等）直建任务：服务端按 `sourceUrl` 找或建 `Opportunity`（按来源域名复用已有 Channel），创建任务并立即认领给当前 Token（20 分钟租约）。仅 `projectId` 与 `sourceUrl` 必填；`workflow` 默认 `directory`（不能为 `unknown`）；`targetUrl` 省略时回落到项目官网；来源域名命中黑名单返回 `422`。同一项目同一来源 URL 已有 `ready / processing / prepared` 任务时返回该任务（重试幂等）；该任务正被其他 Token 持有时返回 `409`。

## Read and update task

```http
GET /api/v1/tasks/10
```

只有领取该任务的 Token 可以读取。

```http
PATCH /api/v1/tasks/10

{"status":"processing"}
```

支持的状态转换：

```text
processing -> processing | completed | failed | skipped
prepared   -> processing | completed | failed | skipped
```

以 `processing` 更新相当于 heartbeat，会将租约延长 20 分钟；切换到其他状态会清除租约。`prepared` 只能由创建 Submission 的接口设置，确保任务状态不会绕过历史记录。

## Submission duplicate check

```http
GET /api/v1/submissions/check?projectId=1&sourceUrl=https%3A%2F%2Fpublisher.example%2Fsubmit
```

```json
{
  "exactSubmissionCount": 1,
  "domainSubmissionCount": 3,
  "domainBacklinkCount": 1,
  "latestStatus": "prepared"
}
```

提示历史重复但不默认禁止操作。

## Create prepared Submission

```http
POST /api/v1/submissions
Idempotency-Key: <uuid>

{
  "taskId": 10,
  "status": "prepared",
  "targetUrl": "https://example.com/product",
  "sourceUrl": "https://publisher.example/submit",
  "workflow": "directory",
  "submittedContent": "Description entered into the form",
  "submittedWebsite": "https://example.com/product",
  "anchorText": "Example",
  "resultMessage": "安全预填 4 个字段"
}
```

创建接口只接受 `prepared`。同一任务、来源 URL 已有 prepared 记录时会更新原记录，避免重复点击产生多条相同历史。创建成功后任务也变为 `prepared`。

历史查询：

```http
GET /api/v1/submissions?projectId=1&limit=50
GET /api/v1/submissions?taskId=10
```

## Update submission result

```http
PATCH /api/v1/submissions/30

{
  "status": "pending",
  "submissionUrl": "https://publisher.example/result",
  "resultMessage": "页面提示 awaiting review",
  "note": "可选人工备注"
}
```

允许写入 `submitted / pending / duplicate / rejected / failed / unknown`。客户端不能直接写入 `published`；`published` 只能由 active Verification 产生。

## Verification

```http
POST /api/v1/verifications
Idempotency-Key: <uuid>

{
  "taskId": 10,
  "submissionId": 30,
  "sourceUrl": "https://publisher.example/result",
  "targetUrl": "https://example.com/product",
  "outcome": "active",
  "anchorText": "Example",
  "linkRel": ["ugc", "nofollow"],
  "checkedAt": "2026-09-02T10:00:00+08:00",
  "message": "当前页面发现精确目标链接"
}
```

Verification outcome：`active / pending / removed / page_404 / link_missing / unknown`。

- `prepared` 不能验证，必须先确认已经执行提交。
- 来源页面必须与任务来源同域，Target URL 必须完全一致。
- `active` 会创建或复用 Channel，再创建/关联 `BacklinkRecord(status=live)`，同时将 Submission 设为 `published`。
- 已发布链接后续验证为 `removed / page_404 / link_missing` 时，Submission 和正式记录都会标记为 removed。
- 非 active 结果只保存 Verification 审计历史，不会创建正式 Backlink。

历史查询：

```http
GET /api/v1/verifications?submissionId=30
GET /api/v1/backlinks/history?projectId=1&limit=50
```

Backlink history 会返回 `origin`：

```text
manual              人工登记，未必独立验证
batch               批量登记，未必独立验证
automation          服务器适配器报告成功
extension_verified  Extension 在真实页面发现精确 Target URL
```

只有 `extension_verified` 表示走过本接口定义的 DOM Verification；不要仅凭 `status=live` 推断所有历史记录都已独立验证。

## Error

```json
{"detail":"当前项目没有可领取的插件任务"}
```

常用状态码：

- `401`：Token 缺失、无效、过期或已撤销。
- `404`：项目、任务不存在，或当前没有待领取任务。
- `409`：Token 不是任务领取者，或状态转换不合法。
- `422`：请求字段不合法。
