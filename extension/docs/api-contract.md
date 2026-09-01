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

本阶段只接受 `prepared`。同一任务、来源 URL 已有 prepared 记录时会更新原记录，避免重复点击产生多条相同历史。创建成功后任务也变为 `prepared`。

历史查询：

```http
GET /api/v1/submissions?projectId=1&limit=50
GET /api/v1/submissions?taskId=10
```

## Error

```json
{"detail":"当前项目没有可领取的插件任务"}
```

常用状态码：

- `401`：Token 缺失、无效、过期或已撤销。
- `404`：项目、任务不存在，或当前没有待领取任务。
- `409`：Token 不是任务领取者，或状态转换不合法。
- `422`：请求字段不合法。

## 后续接口（尚未实现）

```text
PATCH /api/v1/submissions/:id
POST /api/v1/verifications
GET  /api/v1/backlinks/history
```

它们保留在插件 API client 的演进方向中，但当前 UI 不会调用。
