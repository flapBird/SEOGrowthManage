# Backlink Platform：Web 外链管理系统 + Chrome 浏览器执行插件

# 一、项目最终目标

现有项目已经有一个运行在服务器上的 Web 外链管理系统。

现在需要在现有系统基础上进行升级：

> 将其发展为一个完整的 **Backlink Management & Submission Platform**。

整个系统由两个主要部分组成：

```text
Backlink Platform
│
├── Web Dashboard
│   ├── 项目管理
│   ├── 外链机会管理
│   ├── URL Queue
│   ├── 外链提交记录
│   ├── 已发布 Backlink
│   ├── Pending / Failed 管理
│   ├── 外链验证
│   ├── Semrush / CSV 数据导入
│   └── 数据统计
│
└── Chrome Extension
    ├── 当前页面识别
    ├── 页面类型判断
    ├── 正文提取
    ├── AI 内容生成
    ├── 表单识别
    ├── 自动填表
    ├── 用户确认提交
    ├── 页面结果判断
    └── 将结果回写 Web 系统
```

核心架构原则：

```text
Web System = Control Plane
Chrome Extension = Execution Plane
```

即：

* Web 系统负责管理、数据、任务、统计、发现。
* Chrome 插件负责操作用户当前浏览器页面。
* 第三方网站登录状态直接使用当前 Chrome Session。
* Web 系统不保存第三方网站账号密码。
* 不绕过 CAPTCHA / Turnstile / reCAPTCHA / hCaptcha。
* 默认采用半自动模式。
* 每次真正提交动作必须由用户明确触发。
* 遇到未知页面、低置信度、验证码、登录要求时停止并要求人工处理。

---

# 二、Monorepo 改造目标

将 Web 系统和 Chrome Extension 放入同一个 Git Repository。

推荐结构：

```text
backlink-platform/
│
├── apps/
│   ├── web/
│   │   ├── src/
│   │   ├── public/
│   │   └── package.json
│   │
│   └── extension/
│       ├── src/
│       │   ├── background/
│       │   ├── content/
│       │   ├── sidepanel/
│       │   ├── analyzers/
│       │   ├── workflows/
│       │   ├── adapters/
│       │   ├── storage/
│       │   └── utils/
│       │
│       ├── public/
│       ├── manifest.json
│       └── package.json
│
├── packages/
│   ├── shared/
│   │   ├── types/
│   │   ├── constants/
│   │   ├── schemas/
│   │   └── validators/
│   │
│   └── api-client/
│       ├── projects.ts
│       ├── opportunities.ts
│       ├── tasks.ts
│       ├── submissions.ts
│       ├── backlinks.ts
│       └── verification.ts
│
├── package.json
├── pnpm-workspace.yaml
└── README.md
```

优先使用：

```text
pnpm workspace
```

暂时不强制加入 Turborepo。

---

# 三、核心数据模型

系统不要继续使用简单：

```text
URL + status
```

而要建立：

```text
Project
   ↓
Opportunity
   ↓
Task
   ↓
Submission
   ↓
Backlink
```

这些实体必须分开。

---

## 1. Project

表示自己的推广网站。

```ts
interface Project {
  id: string;

  name: string;

  website: string;

  authorName?: string;

  email?: string;

  tagline?: string;

  shortDescription?: string;

  mediumDescription?: string;

  longDescription?: string;

  keywords?: string[];

  createdAt: string;

  updatedAt: string;
}
```

---

## 2. Opportunity

表示发现的潜在外链机会。

```ts
type OpportunityType =
  | "comment"
  | "article"
  | "guest_post"
  | "directory"
  | "forum"
  | "unknown";

interface Opportunity {
  id: string;

  url: string;

  domain: string;

  type: OpportunityType;

  source:
    | "manual"
    | "csv"
    | "semrush"
    | "page_discovery"
    | "competitor_backlink";

  status:
    | "new"
    | "scanned"
    | "eligible"
    | "maybe"
    | "unsupported"
    | "processed";

  opportunityScore?: number;

  hasCommentForm?: boolean;

  hasWebsiteField?: boolean;

  requiresLogin?: boolean;

  hasCaptcha?: boolean;

  pageTitle?: string;

  language?: string;

  discoveredAt: string;

  lastCheckedAt?: string;
}
```

---

## 3. Task

Task 表示实际待插件执行的一次操作。

```ts
interface BacklinkTask {
  id: string;

  opportunityId: string;

  projectId: string;

  workflow:
    | "comment"
    | "article"
    | "guest_post"
    | "directory"
    | "forum";

  status:
    | "ready"
    | "processing"
    | "prepared"
    | "submitted"
    | "completed"
    | "failed"
    | "skipped";

  createdAt: string;

  updatedAt: string;
}
```

---

## 4. Submission

Submission 是最重要的历史记录。

同一个 Opportunity 可以拥有多次 Submission。

```ts
interface Submission {
  id: string;

  taskId: string;

  opportunityId: string;

  projectId: string;

  targetUrl: string;

  targetDomain: string;

  workflow:
    | "comment"
    | "article"
    | "guest_post"
    | "directory"
    | "forum";

  submittedContent?: string;

  submittedWebsite?: string;

  anchorText?: string;

  submissionUrl?: string;

  status:
    | "prepared"
    | "submitted"
    | "pending"
    | "published"
    | "duplicate"
    | "rejected"
    | "failed"
    | "unknown";

  submittedAt?: string;

  verifiedAt?: string;

  resultMessage?: string;

  note?: string;
}
```

---

## 5. Backlink

只有真正验证成功以后才生成 Backlink。

```ts
interface Backlink {
  id: string;

  submissionId: string;

  projectId: string;

  sourceUrl: string;

  sourceDomain: string;

  targetUrl: string;

  anchorText?: string;

  linkType:
    | "dofollow"
    | "nofollow"
    | "ugc"
    | "sponsored"
    | "unknown";

  status:
    | "active"
    | "removed"
    | "page_404"
    | "link_missing"
    | "changed";

  firstSeenAt: string;

  lastCheckedAt?: string;
}
```

---

# 四、Web 系统主要界面

Web Dashboard 至少规划：

```text
Dashboard

Projects

Opportunities

Tasks / URL Queue

Submissions

Backlinks

Pending Review

Verification

Discovery

Semrush

Settings
```

Dashboard 展示：

```text
Projects

New Opportunities

Eligible

Ready Tasks

Submitted

Pending

Published

Rejected

Removed
```

---

# 五、Chrome Extension 主要界面

插件使用：

```text
Manifest V3
+
Side Panel
```

Side Panel 是当前浏览页面的主要操作面板。

示例：

```text
Backlink Assistant

Project
Minecraft Circle Generator ▼

Current Task
example.com/post-a

Workflow
Comment

────────────────

Page Analysis

Comment Form     ✓
Website Field    ✓
Login Required   No
CAPTCHA          No

Opportunity Score
92

────────────────

[ Analyze ]

[ Generate ]

[ Fill Form ]

[ Submit ]

────────────────

Existing Records

This URL:
Never submitted

This Domain:
2 published backlinks
1 pending

────────────────

[ Previous ]
[ Next Task ]
```

---

# 六、Web 与 Chrome 插件通信

系统必须支持两种通信方式。

## 方式 1：插件主动访问 Web API

这是主要方式。

例如：

```text
GET /api/projects

GET /api/tasks/next

GET /api/tasks/:id

POST /api/submissions

PATCH /api/tasks/:id

POST /api/verifications
```

插件从 Web 系统取任务。

流程：

```text
Chrome Extension

↓ Next Task

GET /api/tasks/next

↓

获取 URL

↓

打开页面

↓

执行
```

---

## 方式 2：Web Dashboard 主动唤起插件

Web 页面提供：

```text
Process with Chrome
```

点击以后，通过：

```text
chrome.runtime.sendMessage
```

发送：

```text
taskId
```

给 Extension。

Extension Manifest 配置：

```json
{
  "externally_connectable": {
    "matches": [
      "https://YOUR-WEB-DOMAIN/*"
    ]
  }
}
```

插件使用：

```text
chrome.runtime.onMessageExternal
```

接收任务。

注意：

Web → Extension

只发送：

```text
taskId
```

不要发送：

* 数据库密码
* AI API Key
* 长期 Token
* 第三方网站密码

插件再通过服务器 API 获取实际任务。

---

# 七、Chrome 插件执行模式

最终支持三种模式：

## Manual Assist

```text
Analyze
↓
Generate
↓
Fill
↓
用户自己点击网页 Submit
```

---

## Semi Auto

```text
Analyze
↓
Generate
↓
Fill
↓
插件展示 Preview
↓
用户点击 Confirm Submit
↓
插件点击 Submit
↓
Verify
↓
记录结果
```

这是默认模式。

---

## Trusted Automation

仅为以后预留。

只有：

```text
Known Adapter
+
High Confidence
+
No CAPTCHA
+
No Login Problem
```

才允许进一步自动化。

当前阶段不要实现无人值守批量发布。

---

# 八、分批开发计划

==================================================

# Batch 1

# Monorepo 改造 + Shared Models + Web API 基础

## 背景

现有项目已经有 Web 外链管理系统。

首先不要开始写复杂浏览器自动化。

本批目标是：

> 在保留现有 Web 功能的前提下，把项目改造成 Web + Extension 可以共同开发的 Monorepo，并建立未来所有功能依赖的数据模型和 API。

---

## 要求

首先完整检查现有项目：

```text
package.json
技术栈
数据库
ORM
API
已有页面
已有数据模型
已有外链记录功能
```

不要假定技术栈。

必须优先复用现有：

```text
数据库
ORM
Auth
API Framework
UI Framework
```

不要无必要重写。

---

## Monorepo

调整为：

```text
apps/web
apps/extension
packages/shared
packages/api-client
```

如果现有项目迁移成本较高，可以分阶段调整，但最终目标必须保持这个结构。

---

## Shared Types

加入：

```text
Project
Opportunity
BacklinkTask
Submission
Backlink
```

以及所有 Status Enum。

Web 和 Extension 必须共用这些 Type。

---

## Web API

至少提供：

```text
GET /api/projects

GET /api/opportunities

POST /api/opportunities

GET /api/tasks

GET /api/tasks/next

GET /api/tasks/:id

PATCH /api/tasks/:id

GET /api/submissions

POST /api/submissions

PATCH /api/submissions/:id

GET /api/backlinks

POST /api/backlinks
```

API 命名允许根据当前框架适当调整。

---

## Batch 1 验收

确保：

```text
Web 可以正常启动
原有功能没有被破坏
数据库迁移成功
pnpm workspace 正常
shared package 正常
API 正常
build 正常
```

本批不要实现页面 DOM 操作。

==================================================

# Batch 2

# Chrome Extension 基础 + Side Panel + Web 连接

## 目标

建立 Chrome Extension 执行端。

使用：

```text
Chrome Manifest V3
TypeScript
Side Panel
Content Script
Background Service Worker
```

---

## Side Panel

至少显示：

```text
Server Connection

Current Project

Current Page

Current Task

Analyze Page
```

---

## Web API 连接

实现：

```text
GET Projects

GET Next Task

GET Task
```

Side Panel：

```text
Project ▼

Queue
85 remaining

[ Next Task ]
```

点击 Next：

```text
GET /tasks/next
↓
chrome.tabs.create()
↓
打开目标 URL
```

---

## External Messaging

支持：

```text
Web Dashboard
↓
Process with Chrome
↓
Chrome Extension
```

实现：

```text
externally_connectable
onMessageExternal
```

只允许 Web Dashboard 域名调用。

---

## Batch 2 验收

完成：

```text
Web → Plugin
Plugin → API
Plugin → Open URL
```

完整通信链路。

==================================================

# Batch 3

# 当前页面分析 + Page Type Detector

## 目标

插件能够分析当前页面是什么类型。

识别：

```text
comment

article_editor

guest_post

directory_submission

forum

unknown
```

优先真正实现：

```text
comment
```

其他类型先检测，不执行。

---

## DOM Analyzer

扫描：

```text
form
input
textarea
select
button
iframe
contenteditable
```

读取：

```text
id
name
type
placeholder
aria-label
label
role
parent text
nearby text
```

---

## Comment Detector

识别：

```text
Comment
Name
Email
Website
Submit
```

输出：

```text
selector
confidence
reason
```

Side Panel 可以：

```text
Highlight
```

对应元素。

---

## CAPTCHA / Login Detection

检测：

```text
CAPTCHA
Turnstile
reCAPTCHA
hCaptcha
Login Required
```

只检测。

不得绕过。

==================================================

# Batch 4

# 页面正文提取 + AI 内容生成

## 目标

完成：

```text
Page
↓
Content Extraction
↓
AI
↓
Comment Draft
```

---

## Content Extractor

提取：

```text
Title
Meta Description
H1
Canonical
Language
Article Body
```

清理：

```text
nav
footer
sidebar
comments
ads
related content
cookie banner
```

---

## AI Provider

抽象：

```ts
interface AIProvider {
  generateComment(...): Promise<CommentResult>;
}
```

支持 OpenAI Compatible API。

配置：

```text
Base URL
Model
API Key
```

---

## Comment Generation

生成内容必须：

```text
与正文相关
与页面语言一致
避免模板化
不要生成纯广告
不要默认硬塞网址
```

支持：

```text
Short
Medium
Long
```

生成后用户可以：

```text
Edit
Regenerate
Copy
```

==================================================

# Batch 5

# Project Profile + 自动填写 + Submission Prepared Record

## 目标

加入项目资料并自动填写评论表单。

Project 信息来自 Web。

---

## 自动填写

完成：

```text
Comment → commentDraft

Name → Project.authorName

Email → Project.email

Website → Project.website
```

兼容：

```text
input
textarea
select
contenteditable
React controlled input
Vue
```

触发：

```text
input
change
blur
```

---

## Submission Record

用户点击：

```text
Fill Form
```

以后建立：

```text
Submission
status = prepared
```

这样从第一次真实操作开始就有历史记录。

---

## 查重

填表前检查：

```text
Current URL + Project

Current Domain + Project
```

显示：

```text
This URL already submitted

This domain already has 3 backlinks
```

但只提示，不默认禁止操作。

==================================================

# Batch 6

# 用户确认提交 + Verification + History

## 目标

加入真正的提交生命周期。

流程：

```text
Generate
↓
Fill
↓
Preview
↓
Confirm Submit
↓
Submit
↓
Verify
```

---

## Submit

识别：

```text
Post Comment
Submit Comment
Submit
Reply
Send
```

避免：

```text
Delete
Login
Cancel
Search
Subscribe
```

用户必须点击：

```text
Confirm Submit
```

之后才能触发。

---

## Verification

识别：

```text
Published

Awaiting moderation

Pending approval

Duplicate

Rejected

Spam

Login required

CAPTCHA required

Failed

Unknown
```

更新 Submission：

```text
prepared

→ submitted

→ pending

→ published
```

或者：

```text
rejected
failed
duplicate
```

---

## Backlink Record

只有检测到真正产生链接以后：

```text
Create Backlink
```

记录：

```text
source URL
target URL
anchor
rel
firstSeenAt
```

==================================================

# Batch 7

# Web Backlink CRM + Submission History

## 目标

强化 Web Dashboard。

新增：

```text
Submissions

Backlinks

Pending Review

Domain Detail
```

---

## Submission 页面

支持筛选：

```text
Project

Status

Workflow

Domain

Source

Date
```

显示：

```text
Domain

Target URL

Project

Type

Status

Submitted At

Result

Published URL
```

---

## Domain Detail

例如：

```text
example.com

Opportunities   16
Submissions      5
Published        3
Pending          1
Rejected         1
```

下面显示全部历史记录。

---

## Backlinks

展示：

```text
Source URL
Target URL
Project
Anchor
Rel
First Seen
Last Checked
Status
```

支持：

```text
Active
Removed
404
Missing
Changed
```

==================================================

# Batch 8

# URL Queue + Opportunity Scanner

## 目标

将单页处理升级为候选 URL 管理。

支持：

```text
Paste URLs

CSV Import

Manual Add
```

URL 进入：

```text
Opportunity
```

---

## Scanner

识别：

```text
Comment Form

Website Field

Login

CAPTCHA

Page Type

Language
```

生成：

```text
Opportunity Score
```

例如：

```text
Comment form        +30
Website field       +30
No login            +15
No captcha          +10
Content detected    +10
High confidence      +5
```

---

## Queue UI

```text
Todo

Scanned

Eligible

Maybe

Unsupported

Processed
```

用户可以：

```text
Open & Process
```

处理完成：

```text
Next Task
```

==================================================

# Batch 9

# Article / Directory / Forum Workflow

## 目标

在 Comment Workflow 稳定以后再扩展。

Workflow Router：

```text
comment
→ CommentWorkflow

article_editor
→ ArticleWorkflow

directory_submission
→ DirectoryWorkflow

forum
→ ForumWorkflow
```

---

## Article Workflow

支持检测：

```text
Title

Slug

Body

Excerpt

Category

Tags

Save Draft

Publish
```

建立：

```text
EditorAdapter
```

逐步支持：

```text
textarea

contenteditable

TinyMCE

CKEditor

Quill

TipTap

ProseMirror

WordPress
```

不得一次强行支持全部。

---

## Directory Workflow

映射：

```text
Project Name

URL

Tagline

Description

Category

Tags

Email
```

数据主要来自 Project Profile。

---

# Batch 10

# Semrush / Discovery Engine

## 目标

最后再做自动发现 URL。

Discovery Engine 与浏览器执行系统完全解耦。

支持：

```text
Semrush API

Semrush CSV

Manual CSV

Page Discovery
```

---

## Semrush

流程：

```text
Competitor Domain

↓

Semrush Backlinks

↓

Referring Pages

↓

Normalize

↓

Deduplicate

↓

Opportunity

↓

Scanner
```

---

## 评论区外部域名发现

插件可以扫描评论区已有：

```text
a[href]
```

提取其他评论者 Website 域名。

过滤：

```text
当前域名

Google

Facebook

X

Instagram

LinkedIn

YouTube

CDN
```

用户可以：

```text
Add to Discovery
```

然后服务器进一步通过 Semrush 获取其外链。

---

# 九、最终完整工作流

最终应该形成：

```text
                       Web Dashboard
                              │
                 ┌────────────┴────────────┐
                 │                         │
             Discovery                 Management
                 │                         │
        Semrush / CSV / Manual      Projects / CRM
                 │                         │
                 └────────────┬────────────┘
                              ↓
                         Opportunity
                              ↓
                          URL Queue
                              ↓
                             Task
                              ↓
                      Chrome Extension
                              ↓
                     Page Type Detector
                              ↓
          ┌───────────────────┼───────────────────┐
          ↓                   ↓                   ↓
       Comment             Article            Directory
       Workflow            Workflow           Workflow
          ↓                   ↓                   ↓
             Content Generation
                      ↓
                 Form Analyzer
                      ↓
                  Form Filler
                      ↓
                  User Review
                      ↓
               Confirm Submit
                      ↓
                 Verification
                      ↓
                  Submission
                      ↓
              Published Backlink
                      ↓
               Backlink Monitoring
```

---

# 十、重要开发原则

## 1. 不重写现有 Web 系统

必须：

```text
Inspect first
Modify second
```

优先复用：

```text
现有数据库
现有 Auth
现有 ORM
现有组件
现有 API
现有 UI
```

---

## 2. Detection 与 Action 分开

例如：

```text
detectSubmitButton()
```

不能同时：

```text
clickSubmitButton()
```

---

## 3. AI 与浏览器操作完全分开

AI：

```text
生成草稿
```

Browser Automation：

```text
识别和填写 DOM
```

两者禁止耦合。

---

## 4. Web 与 Extension 共用数据结构

所有核心 Type：

```text
packages/shared
```

禁止 Web 和 Extension 各自维护不同 Status。

---

## 5. Submission 与 Backlink 必须分开

提交成功：

不代表：

外链已经发布。

因此：

```text
Submission
```

和：

```text
Backlink
```

必须是两个实体。

---

## 6. 所有自动化必须可观察

禁止 silent failure。

Side Panel 必须显示：

```text
当前 Task

当前 Workflow

检测结果

Confidence

生成内容

即将填写的数据

填写结果

Submit Button

Verification Result

Submission Status
```

---

## 7. Low Confidence 时停止

遇到：

```text
Unknown Form

Unknown Editor

Multiple Forms

Low Confidence

CAPTCHA

Login Required

Unknown Submit Button
```

显示：

```text
Manual Review Required
```

禁止强行继续。

---

# 十一、每个 Batch 的 Codex 执行要求

每次执行一个 Batch。

开始之前：

1. 阅读整个项目结构。
2. 阅读上一批实现。
3. 检查 git diff。
4. 理解已有代码后再修改。
5. 不回滚此前已经完成的功能。
6. 不擅自开始下一 Batch。

完成以后必须运行项目当前可用的：

```text
lint

typecheck

tests

build
```

Chrome Extension 还必须验证：

```text
chrome://extensions

Developer mode

Load unpacked
```

可以正常加载。

每批结束以后输出：

```text
1. 本批完成内容

2. 新增文件

3. 修改文件

4. 数据库 Migration

5. 新增 API

6. 核心设计决定

7. 测试方式

8. 已知限制

9. 下一批可以直接复用的接口
```

如果测试发现问题，应优先修复，而不是把问题推给下一批。

---

# 十二、当前执行要求

现在只执行：

## Batch 1：Monorepo 改造 + Shared Models + Web API 基础

不要执行 Batch 2 或后续内容。

首先完整检查当前已有 Web 外链管理系统。

在尽可能少破坏现有代码的情况下完成 Batch 1。

如果当前项目技术架构与上述目录略有不同，可以根据现状做合理调整，但必须保持：

```text
Web App

Chrome Extension App

Shared Types

Shared API Client
```

四者长期解耦的总体方向。
