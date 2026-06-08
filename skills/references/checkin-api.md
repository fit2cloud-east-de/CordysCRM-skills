# 打卡系统 API 参考

基础地址：`CHECKIN_API_URL` 环境变量（从技能目录下的 `.env` 读取）

---

## 创建打卡任务

AI 在对话中收集完所有必填字段后调用此接口，字段会暂存到 token 中，用户点击链接后只需获取定位即可完成打卡。

本接口只创建打卡任务和临时 token，不写入打卡记录表。无论是公司打卡还是拜访打卡，都必须等用户点击卡片并完成定位后，才由 `submit-checkin` 写入打卡记录表。

```
POST /api/wechat/create-checkin
Content-Type: application/json
```

### 请求体

| 字段 | 必填 | 说明 |
|------|------|------|
| userid | 是 | 用户标识，直接取对话上下文中的 `sender_id`。不要猜测、不要追问、不要尝试转换格式，原样传入即可 |
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
| webhookUrl | 否 | 回调地址。不要手写，`checkin.sh` 会从 `.env` 的 `OPENCLAW_WEBHOOK_URL` 自动注入；未配置则不传 |

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

由 H5 页面自动调用，用户无需手动操作。技能侧如需手动触发，可运行 `bash scripts/checkin.sh submit-checkin '<JSON>'`。

这是打卡系统的写表动作：`create-checkin` 只创建任务和 token，不代表用户已打卡；`submit-checkin` 才会根据 token 中暂存的字段和本次定位结果写入打卡记录表，并在完成后触发 webhook 通知。

写表时机必须满足两个条件：用户点击打卡卡片，且 H5 完成定位提交。纯跟进只写 CRM 跟进记录，不创建打卡任务，也不写入打卡记录表。

出于隐私和安全考虑，skill 文档只描述"打卡记录表"这个业务概念，不暴露真实数据库表名、表结构、内部字段名、连接串或存储实现。

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
  "source": {"icon_url": "<CHECKIN_API_URL>/cordys-favicon.png", "desc": "公司打卡", "desc_color": 0},
  "emphasis_content": {"title": "点击打卡"},
  "horizontal_content_list": [{"keyname": "部门", "value": "{所在部门}"}],
  "jump_list": [{"type": 1, "title": "手机打卡效果更佳哦", "url": "{link}"}],
  "card_action": {"type": 1, "url": "{link}"}
}
```

### 拜访打卡卡片

补充字段（有值时填入，无值时省略）：`contact`（联系人）、`followContent`（跟进内容摘要，取用户原始输入的业务描述部分，不超过20字）、`stageName`（商机阶段，从搜索结果的 `stageName` 字段获取，仅商机型记录有值）、`products`（意向产品）

```json
{
  "card_type": "text_notice",
  "source": {"icon_url": "<CHECKIN_API_URL>/cordys-favicon.png", "desc": "{打卡类型}", "desc_color": 0},
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

## Webhook 通知

`webhookUrl` 用于接收打卡完成/失败通知。通知的转发由平台已有回调能力处理，skill 只负责在创建打卡任务时把回调地址交给打卡系统，不重复定义回调消息处理流程。

---

## 错误处理

| error_type | 含义 | 处理 |
|------------|------|------|
| auth | 认证失败（401/403） | 提示检查 CRM 配置 |
| config | 未配置（缺少必填字段） | 提示配置 .env |
| business | 业务逻辑错误 | 展示错误信息 |
| server | 服务端错误（500/502/503） | 提示稍后重试 |
| network | 网络连接失败 | 提示稍后重试 |
