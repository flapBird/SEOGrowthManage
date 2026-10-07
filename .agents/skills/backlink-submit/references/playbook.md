# 渠道提交攻略（playbook）

字段映射、结果判定、通用流程都在本文件；SKILL.md 只讲步骤顺序。入口 URL 以站内实际为准——清单里的 submit_url 只是参考，进站后**必须**从真实页面找 Submit/Add/Launch 入口，禁止盲信硬编码路径。

## SideProjectors（sideprojectors.com）✅ 已跑通的参考渠道（2026-09 实测，14 站成功）

免登录探测结论：需登录；showcase 提交免费。**批量提交流程已固化为 `scripts/sp_run.py`**（一个站点一条命令跑完 10 阶段），手动手册如下：

1. **入口**：登录后 `+ SUBMIT A PROJECT` → 选 "🎉 I want to promote / showcase my project"（展示模式，不涉及出售）
2. **抓取快捷方式**：展开 "Fetch information from the project homepage" 卡片 → 填站点 URL → Submit → 自动建草稿并抓取名称/描述/og-image（草稿在 My Projects → Drafts，编辑链接 `/submit/project/<id>/general`）
3. **6 步向导**：
   - **General**：type 选 Website / Web Application；名称用站点品牌名（≤50 字符，meta title 可能超限要手改）；pitch **≤80 字符**；描述是 Quill 富文本（用 execCommand insertText 写入）；**Markets** 必填（最多 5 个）——vue-multiselect 是 toggle 行为：**单会话只能稳定选 1 个**，每会话选完即存（草稿 autosave），选重复会取消
   - **Media**：上传截图 + 点 ADD → ajax-loader 转完出现 Delete 缩略图才算成功。⚠️ 三个坑：(a) 抓取步骤会预附着站点 og-image（很多是纯色背景图），要删掉重传真实截图；(b) **无头自动化环境下图片上传不可靠**——实测仅个别成功，其余 ADD 后 policy 请求不发出或 XHR 挂起（已排除：会员限制——用户手动上传正常、自动化检测——有头模式同样失败、og 占位、会话切分）；(c) 失败会残留"转圈中"的幽灵条目，需先 Delete 再传。**纪律：此渠道的媒体上传默认交给用户手动完成**（素材在 assets/<域名>/），自动化仅做文字字段
   - **Built-with**：必填至少一项技术栈（Languages 搜 javascript）
   - **Metrics**：可全跳过（没有真实流量数据不要编）
   - **Sale discussion**："愿意讨论出售" 默认勾选——这是业务立场，保留默认并在报告里提醒用户可改
   - **Confirm**：勾真实性声明 + 开 ComingUp 免费同步开关（sr-only checkbox，在 ComingUp 卡片内；开启后 SP 过审会自动提交到 comingup.io）→ Next → 🎉 done，2-3 天审核
4. **审核期项目页私密**：公开访客看 `/project/<id>` 是 "Project not found"，**验证外链必须用匿名视角**（无登录态上下文），审核通过后重新验证
5. **提交后编辑**：`/submit/project/<id>/media` 等向导页对已提交项目仍可访问，改动后点 "Save & Publish Later" 保存
6. 批量修复媒体用 `scripts/fix_media.py`（删 og 引用 → 传真实截图 → 验证 R2 存储路径 → 保存）

## 通用流程（每个渠道都走这一遍）

1. 开后台窗口 → 首页 → 读 innerText 判登录态
2. 未登录：记 `needs_login`，请用户登录后继续；**绝不注册新账号**
3. 从页面找提交入口（关键词 `Submit / Add / Launch / Post / List your / 加入`）
4. 列出表单字段（name/id/placeholder）→ 按"字段映射"逐空填入
5. 提交按钮按"按钮分类"识别
6. 提交后按"结果判定"定 status → `api.py result` 回写 → 结果页搜目标域名，找到则 `api.py verify`

## 字段映射（profile → 表单）

| 表单字段（常见叫法） | 取值 |
|---|---|
| Name / Product name / Title | profile.name |
| Website / URL / Link | profile.url |
| Email / Contact | profile.email |
| Tagline / Short pitch / One-liner（≤60字符类） | profile.tagline |
| Description / Summary / Intro（1-2 句） | profile.short_description |
| Detailed description / About | profile.medium_description（超长时截到字段上限） |
| Full description / Article body | profile.long_description |
| Keywords / Tags / Categories | profile.keywords + 站内最接近的分类 |
| Logo / Image | 无 L2 时留空说明；必填则停（needs_upload） |

纪律：英文渠道用英文资料；描述里自然带上产品名和链接，**不写 "best/№1/free trial" 式广告语**；有 "How did you hear about us" 类非关键字段可留空。

## 按钮分类（提交前必查 label）

- 绝不点：`delete|remove|cancel|search|subscribe|login|sign in|reset|back|删除|取消|搜索|订阅|登录|返回`
- 仅推进多步表单（status 保持 prepared）：`next|continue|get started|下一步|继续|开始`
- 真提交：`submit|publish|launch|post|send|add listing|add product|提交|发布|上线`

## 结果判定（结果页 innerText，与扩展 detectSubmissionOutcome 一致）

| 顺序 | 正则（不分大小写） | status |
|---|---|---|
| 1 | `awaiting moderation|pending approval|under review|待审核|审核中` | pending |
| 2 | `duplicate|already submitted|already exists|重复提交|已经提交` | duplicate |
| 3 | `rejected|not approved|marked as spam|垃圾内容|spam detected` | rejected |
| 4 | `captcha required|complete the captcha|please log in|login required|sign in to continue|需要登录|验证码` | failed（note 写明原因） |
| 5 | `submission failed|could not submit|something went wrong|an error occurred|提交失败` | failed |
| 6 | `thank you|successfully submitted|submission received|has been posted|提交成功|感谢提交|已收到` | submitted |
| — | 以上都不中 | unknown（note 保存页面关键句，≤200字符） |

## Tier 1 渠道要点（≥5 票，按推荐票排序）

### 发布平台类（category=launch）

- **Product Hunt**（72票）入口：登录后右上角 "+" → Post a product（/posts/new）。流程多步：名称→tagline≤60字符→链接→topics→logo(≥240×240)→gallery→Maker 首评。logo 上传必填，L1 做不了 → 到上传步时降级 L2 或让用户手动。发布时间建议工作日。
- **Fazier**（16票，有付费位）入口：登录后 Launch（/launch，以站内为准）。免费排队上线，付费置顶——选免费。
- **BetaList**（9票，有付费位）入口：/submit。需要已上线的 MVP + 能截图的 landing page；排队免费、加急收费（清单备注：价格不贵）；审核较严，提前做好 landing page。
- **Uneed**（10票，有付费位）入口：/submit 或 Launch 区（以站内为准）。免费排队发布，月访问 171.9k。
- **TinyLaunch**（6票）、**ToolPilot**（6票，有付费位）、**microlaunch.net**（5票）、**PromoteProject**（15票）、**SideProjectors**（10票，可导入 Product Hunt 产品）、**Startup Fame**（10票，有付费位，挂徽章一周内过）：免费提交，进站找 Submit/Add 入口即可。
- **f6s.com**（8票）：建公司/产品资料页。**SourceForge**（8票）：仅适合开源项目。**V2EX**（26票，有付费位）：登录后 /new 选"分享创造"节点；新号发帖受限；中文、别写成广告。
- **Indie Hackers**（14票）：发 product page 或 milestone 帖，重真实经历。
- **Peerlist**（12票）：Launchpad 提交，需登录。

### AI 目录类（category=ai-directory）

- **There's An AI For That**（57票，有付费位）入口：登录后 /submit。免费排队人工审核，通过即入库；审核数天到数周，结果回写 pending。
- **Toolify**（44票，有付费位）入口：/submit（支持 Google 登录）。反馈快；需要英文资料。
- **Dang.ai**（15票）：免费提交**需先挂徽章**（把 backlink 加到自己网站后提交），DR81。needs_badge 流程：先让用户在站点加徽章，或跳过。
- **TopAI.tools**（10票）、**futurepedia.io**（6票，有付费位）、**aitoolsdirectory.com**（6票，有付费位）、**AIxploria**（5票）、**AIToolly**（5票，有付费位）：免费提交通道+可选付费加速，一律选免费。
- **twelve.tools**（7票，有付费位）、**Findly.tools**（5票）：免费提交需挂徽章。
- Tier2 常见（gptdemo/listedai/turbo0/saasaitools/aistage/aitoolboard/aitoolguru/aitools.fyi 等）：同一模式，进站找 Submit。

### 软件目录/评论类（category=review / software-directory）

- **SaaSHub**（31票，有付费位）：登录后 Add Application；免费收录。
- **AlternativeTo**（15票，有付费位）：先搜产品名防重复 → Add application；需选 license/platform/tags。
- **G2**（11票，有付费位）/ **Capterra**（6票）/ **getapp.com**（7票）：三者同属 Gartner Digital Markets，走 "List your software for free" 流程，**一次提交通常覆盖三家**；需要公司邮箱做验证，验证邮件可能到 profile.email —— 如邮箱不是企业邮箱可能被拒，note 说明。
- **Trustpilot**（5票）：Claim business profile 免费域名认领，需要邮箱验证。
- **saasworthy.com**（4票）：提交工具收录。

### 博客/文章类（category=blog）——默认 confirm 模式

- **DEV Community**（16票）：写一篇真实的 build log / how-to（≥300字），文末带产品链接；禁止批量低质内容（封号风险）。
- **Medium**（16票）：medium.com/new-story 发文，文内嵌链接。
- **Substack**（10票）/ **Blogger**（11票）/ **Hashnode**（5票）：开刊物/博客发文。Blogger 用 Google 账号。
- **zhihu.com**（5票）：知乎专栏中文文章。

### 社区类（category=community）——默认 confirm 模式，先读版规

- **Hacker News**（24票）：news.ycombinator.com/submit；标题 `Show HN: <名称> – <一句话>`，链接直指产品，不带营销语；nofollow。
- **Reddit**（16票）：先开目标 subreddit 的 Rules 页确认允许自我推广（r/SideProject 等宽松，多数技术版块禁止）；贴文文案必须像人话。
- **Quora**（5票）/ **Stack Overflow**（4票）：回答真实相关问题，链接放正文，禁止无中生有提问。

### 社交/档案类（category=social / profile / repo）——默认 confirm 模式

- **GitHub**（30票）：不是表单提交——Profile README、仓库 README、Awesome 列表 PR。需要用户已有仓库策略。
- **X**（7票）/ **LinkedIn**（6票）/ **Facebook / Instagram / Pinterest / YouTube**（各≤5票）：发帖/发文/发视频带链接，内容与渠道调性匹配。
- **Crunchbase**（11票）：/organization/new 建公司资料（免费档）。
- **about.me / gravatar / start.me / solo.to**：个人页加链接。

## Tier 2/3 长尾渠道

无逐站攻略，按 category 用上面的通用模式；1 票长尾（tier 3）**未经社区验证**，提交前先看站内是否真有免费提交入口，站不像目录/没有入口的记 `skipped`（note: 无提交入口），不要硬凑。

## 挂徽章类渠道的处理

清单中标注"挂徽章后通过"的渠道（Dang.ai、twelve.tools、Findly.tools、Startup Fame 等）需要先把徽章代码放到产品官网。这是对用户官网的改动 → 记 `needs_badge`，向用户确认是否挂徽章，用户同意后引导其操作（或在用户明确授权下由技能在官网代码里加），之后重跑该渠道。
