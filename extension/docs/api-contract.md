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
    "website": "https://example.com"
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
  "updatedAt": "2026-09-01T10:00:00"
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

{"status":"prepared","note":"页面已检查，等待提交"}
```

支持的状态转换：

```text
processing -> processing | prepared | completed | failed | skipped
prepared   -> processing | completed | failed | skipped
```

以 `processing` 更新相当于 heartbeat，会将租约延长 20 分钟；切换到其他状态会清除租约。

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
POST /api/v1/submissions
POST /api/v1/verifications
GET  /api/v1/backlinks/history
```

它们保留在插件 API client 的演进方向中，但当前 UI 不会调用。
