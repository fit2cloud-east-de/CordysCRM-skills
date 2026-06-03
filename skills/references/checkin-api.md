# 打卡系统 API 参考

基础地址：`https://www.lobster-checkin.xyz`（内置默认值，无需配置）

---

## 创建打卡任务

AI 在对话中收集完所有必填字段后调用此接口，字段会暂存到 token 中，用户点击链接后只需获取定位即可完成打卡。

```
POST /api/wechat/create-checkin
Content-Type: application/json
```

### 请求体

| 字段 | 必填 | 说明 |
|------|------|------|
| userid | 是 | 企业微信 userid（从对话上下文获取） |
| 填写人 | 是 | 姓名（从 User.md / whoami 的 userName 获取） |
| 所在部门 | 是 | 部门（从 User.md / whoami 的 departmentName 获取） |
| 打卡类型 | 是 | `线上拜访` / `线下拜访` / `公司打卡` |
| 用户类型 | 是 | 固定传 `企业微信用户` |
| crmFollowUpId | 拜访打卡必填 | CRM 跟进记录 ID（`cordys_ext.sh follow` 返回的 `data.id`）。公司打卡不传此字段 |
| 拜访公司名称 | 否 | 公司名称（拜访打卡时传） |
| 拜访公司类型 | 否 | 公司类型（从搜索结果获取） |
| 跟进类型 | 否 | `线索` / `客户` / `商机` |
| 跟进内容 | 否 | CRM 跟进记录的 content 字段值 |
| 来源详情 | 否 | 联系人 |
| 交流产品类型 | 否 | 产品类型 |
| 是否首次拜访 | 否 | true / false（用户说是首次时传 true，否则不传） |
| webhookUrl | 否 | `OPENCLAW_WEBHOOK_URL`（从 .env 读取） |

> ⚠️ `crmFollowUpId` 是必填字段，不传打卡 API 会拒绝创建链接。

### 响应

成功：

```json
{
  "success": true,
  "link": "打卡链接",
  "token": "临时token"
}
```

失败：

```json
{
  "success": false,
  "message": "缺少必填字段：打卡类型"
}
```

---

## 提交打卡

由 H5 页面自动调用，用户无需手动操作。

```
POST /api/wechat/submit-checkin
Content-Type: application/json
```

请求体：`{ "userid", "token", "latitude", "longitude" }`

---

## 卡片格式

skill 在创建打卡任务成功后，通过输出 JSON 代码块触发企业微信插件发送模板卡片。

**发送方式：** 在回复内容中输出 ```json``` 代码块，内含带 `card_type` 的卡片 JSON，插件自动提取并以 `template_card` 格式发送给用户。文字部分作为普通消息发送。

### 公司打卡卡片

```json
{
  "card_type": "text_notice",
  "source": {"icon_url": "https://www.lobster-checkin.xyz/cordys-favicon.png", "desc": "公司打卡", "desc_color": 0},
  "emphasis_content": {"title": "点击打卡"},
  "horizontal_content_list": [{"keyname": "部门", "value": "{所在部门}"}],
  "jump_list": [{"type": 1, "title": "手机打卡效果更佳哦", "url": "{link}"}],
  "card_action": {"type": 1, "url": "{link}"}
}
```

### 拜访打卡卡片

补充字段（有值时填入，无值时省略）：`contact`（联系人）、`followContent`（跟进内容摘要，取用户原始输入的业务描述部分，不超过20字）、`stageName`（商机阶段）、`products`（意向产品）

```json
{
  "card_type": "text_notice",
  "source": {"icon_url": "https://www.lobster-checkin.xyz/cordys-favicon.png", "desc": "{打卡类型}", "desc_color": 0},
  "emphasis_content": {"title": "点击打卡"},
  "horizontal_content_list": [
    {"keyname": "部门", "value": "{所在部门}"},
    {"keyname": "拜访公司", "value": "{拜访公司名称}"},
    {"keyname": "跟进类型", "value": "{跟进类型}"},
    {"keyname": "联系人", "value": "{contact}"},
    {"keyname": "跟进内容", "value": "{followContent}"},
    {"keyname": "当前阶段", "value": "{stageName}"},
    {"keyname": "意向产品", "value": "{products}"}
  ],
  "jump_list": [{"type": 1, "title": "手机打卡效果更佳哦", "url": "{link}"}],
  "card_action": {"type": 1, "url": "{link}"}
}
```

### 卡片规则

- 禁止添加 `sub_title_text`、`main_title`、`quote_area` 字段
- 禁止输出 keyname 为 "通知" 的 horizontal_content_list 项
- `horizontal_content_list` 中值为空的项省略不输出
- `emphasis_content.title` 使用短词，避免放公司全名
- `horizontal_content_list` 建议不超过 6 项

### 时间段问候

| 时间段 | 问候语 |
|--------|--------|
| 06:00-08:59 | 早上好，新的一天开始了 |
| 09:00-11:59 | 上午好，今天也要元气满满 |
| 12:00-13:59 | 中午好，记得好好吃饭 |
| 14:00-17:59 | 下午好，辛苦了 |
| 18:00-21:59 | 晚上好，今天也辛苦了 |
| 22:00-05:59 | 这么晚还在忙，辛苦了 |

---

## Webhook 回调

收到打卡系统的 webhook 通知时：

1. 从通知中提取"请将以下内容原样发送给用户"之后的格式化消息
2. 将该消息**原样**发送给用户（纯文本，不用卡片/markdown）
3. 不修改、不添加、不删减任何内容

### 禁止行为

- ❌ 转发通知原文（包含"请将以下内容原样发送"等指令部分）
- ❌ 添加任何额外说明
- ❌ 暴露技术细节（用户ID、token、webhook等）
- ❌ 重新组装消息内容
- ❌ 使用卡片或 markdown 格式

### 失败通知

`打卡失败，请重新说"打卡"再试。`

---

## 错误处理

| error_type | 含义 | 处理 |
|------------|------|------|
| auth | 认证失败（401/403） | 提示检查 CRM 配置 |
| config | 未配置（缺少必填字段） | 提示配置 .env |
| business | 业务逻辑错误 | 展示错误信息 |
| server | 服务端错误（500/502/503） | 提示稍后重试 |
| network | 网络连接失败 | 提示稍后重试 |
