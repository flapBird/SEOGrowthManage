# 浏览器控制：本机谷歌 Chrome（backlink-submit）

## 零打扰原则（最高优先级，2026-09-19 实测教训）

**绝不通过 AppleScript 驱动用户正在使用的 Chrome**——新建窗口、切标签页、最小化窗口都会打断用户操作，用户明确投诉过。唯一正确方式：

- 用 `scripts/browser.py`（Playwright `channel="chrome"` + `headless=True` + 独立 profile `~/.seo-chrome-profile`）驱动**本机 Google Chrome 本体**：同一浏览器、无窗口、独立配置目录，登录态在 profile 里持久化
- 命令：`browser.py open <url>` / `browser.py run <url> '<js>'` / `browser.py text <url>`；JS 写单行 IIFE 返回 `JSON.stringify(...)`
- **需要用户登录时**：让用户跑 `open -na "Google Chrome" --args --user-data-dir=$HOME/.seo-chrome-profile --no-first-run` 在同一 profile 里登录（此时暂停 browser.py 调用避免 profile 锁冲突），登录完用户 Cmd+Q 该实例后继续无头驱动
- osascript 方案仅保留作历史参考，不再使用

## （历史方案）L1 osascript 执行 JS —— 已弃用

~~提交外链必须用用户本机的 Google Chrome（登录态都在里面）。所有动作走后台窗口，绝不占用用户当前标签页，用完关闭自己开的窗口。~~

以下旧内容仅供参考，不要再执行。

## 每轮开始前的检查（只做一次）

1. Chrome 是否在运行：`pgrep -x "Google Chrome" >/dev/null && echo running`；未运行则 `open -a "Google Chrome"`（会启动真实 Chrome）
2. Apple Events JS 是否可用（L1 通道开关）：

```bash
osascript -e 'tell application "Google Chrome" to execute (active tab of front window) javascript "document.title"' 2>&1
```

- 返回了标题字符串 → L1 可用
- 报"执行 JavaScript 被禁用 / Not authorized"类错误 → 请用户开启 Chrome 菜单 **显示 > 开发者 > 允许 Apple 事件中的 JavaScript**；用户拒绝开启则全程走 L2

## L1：osascript 执行 JS（主通道，快且稳）

### 开后台工作窗口并记住窗口 id

```bash
WINID=$(osascript -e 'tell application "Google Chrome"
  set w to make new window
  set URL of active tab of w to "https://example.com/submit"
  return id of w
end tell' | tr -d '"')
```

后续所有操作都绑定 `window id $WINID`，不受用户切换窗口影响。

### 等待与读取

```bash
# readyState 轮询：SPA 站点 DOM 就绪≠可交互，读不到目标元素就 sleep 2 重试（最多 5 次）
osascript -e "tell application \"Google Chrome\" to execute (active tab of window id $WINID) javascript \"document.readyState\""

# 读正文（≤5000 字符，够识别登录态和提交入口）
osascript -e "tell application \"Google Chrome\" to execute (active tab of window id $WINID) javascript \"document.body.innerText.slice(0,5000)\""
```

Cloudflare 挑战页（页面只有 "Just a moment"）：等 6 秒后 `set URL of active tab of window id $WINID to <同URL>` 重载一次；再失败记 `failed` 跳过该渠道，不要反复硬闯。

### 登录态检测（每站必做）

读 body innerText 后判断：出现醒目的 `Sign in / Log in / Sign up / 登录 / 注册` 作为主 CTA 且没有头像/用户名/Dashboard 证据 → 未登录 → 记 `needs_login`，请用户自己在 Chrome 登录该站后说"继续"，不要替用户注册新账号。

### 填表模式

先注入一次 fill helper（同一页面内 `window.__setVal` 会一直留存，后续直接用）：

```bash
osascript -e "tell application \"Google Chrome\" to execute (active tab of window id $WINID) javascript 'window.__setVal=function(el,v){var p=el instanceof HTMLTextAreaElement?HTMLTextAreaElement.prototype:el instanceof HTMLSelectElement?HTMLSelectElement.prototype:HTMLInputElement.prototype;Object.getOwnPropertyDescriptor(p,\"value\").set.call(el,v);el.dispatchEvent(new Event(\"input\",{bubbles:true}));el.dispatchEvent(new Event(\"change\",{bubbles:true}));el.dispatchEvent(new Event(\"blur\",{bubbles:true}))};\"helper ready\"'"
```

逐字段填入（React/Vue 表单必须经 input/change 事件，直接 `el.value=` 无效）：

```bash
osascript -e "tell application \"Google Chrome\" to execute (active tab of window id $WINID) javascript 'var el=document.querySelector('\"'\"'input[name=\"website\"]'\"'\"');el&&el.value===\"\"?window.__setVal(el,\"https://product.example/\"):\"skip\"'"
```

- **只填空字段**（`el.value===""` 才填），已有内容不覆盖——与 Chrome 扩展同一安全边界
- 选择器必须来自真实 DOM：先用 `document.querySelectorAll('input,textarea,select')` 列出字段的 name/id/placeholder/aria-label，再写选择器，禁止猜
- JS 内字符串尽量用单引号 + `\"` 转义；复杂脚本写成一行，或写入临时文件后 `$(cat /tmp/fill.js)` 展开
- `document.querySelector` 返回 null 时 osascript 会报错或返回空——先存在性检查再赋值

### 点击与提交按钮识别

提交/下一步按钮识别正则（与扩展 submitController 同一套，防误点）：

- 危险/非提交（绝不能点）：`delete|remove|cancel|search|subscribe|login|sign in|reset|back|删除|取消|搜索|订阅|登录|返回`
- 仅推进多步表单（点了 Submission 仍是 prepared）：`next|continue|get started|下一步|继续`
- 真提交：`submit|publish|launch|post|send|add listing|add product|提交|发布|上线`

auto 模式下点击真提交前必须：按钮 label 语义唯一明确 + 无 CAPTCHA + 无付费墙。点击用 `document.querySelector('button[type=submit]').click()`。

### L1 做不到的事（直接降级，别硬试）

- **文件上传**（logo/图片）：execute JS 无法触发文件选择，降级 L2 computer-use 操作文件对话框，或请用户手动上传后说"继续"
- **拖拽/日历等复杂组件**：降级 L2
- **iframe 里的表单**：execute JS 默认在顶层 frame，跨域 iframe 摸不到 → 降级 L2

## L2：computer-use 可访问性控制（降级通道）

适用：L1 不可用（用户没开 Apple Events JS）、文件上传、跨域 iframe、复杂组件。

流程：`get_app_state`（app_ref 用 Chrome 的 pid）读元素树 → 对元素目标 `left_click` / `type` / `set_value`；文件对话框用 `key` 输入路径（`Cmd+Shift+G` 后输入绝对路径 + Return）。操作前后各观察一次确认生效。Chrome 不必切到前台即可被控制，但涉及文件面板时需要确认窗口已聚焦。

## L3：内置浏览器（browser-use）

**只用于明确无需登录的渠道**（Telegraph、少数匿名目录表单）。内置浏览器没有用户登录态，需要账号的渠道一律走 L1/L2。L1/L2 都可用时优先 L1。

## 每渠道页面预算与退出

- 每渠道最多访问 ~5 个页面：首页（登录检测）→ 提交页 → 最多 2 个多步表单步 → 结果页
- 任何一步连续失败 3 次就停，记台账（status + note 含失败原因），继续下一渠道，绝不中断整轮
- 用完关闭工作窗口：`osascript -e "tell application \"Google Chrome\" to close (window id $WINID)"`
