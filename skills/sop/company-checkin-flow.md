# 公司打卡流程

用户说"打卡""签到""上班""到公司"时执行本流程。不涉及 CRM，只创建打卡链接。

---

## 步骤 1：企业微信判断

检查对话上下文中是否有企业微信 userid：

- **有** → 继续步骤 2
- **无** → 提示"请在企业微信中发起打卡"，结束

---

## 步骤 2：创建打卡链接

打卡 API 请求/响应格式详见 `references/checkin-api.md`。

```bash
curl -s -X POST https://www.lobster-checkin.xyz/api/wechat/create-checkin \
  -H "Content-Type: application/json" \
  -d '{
    "userid": "<企业微信userid>",
    "填写人": "<User.md 中的姓名>",
    "所在部门": "<User.md 中的部门>",
    "打卡类型": "公司打卡",
    "用户类型": "企业微信用户",
    "webhookUrl": "<OPENCLAW_WEBHOOK_URL>"
  }'
```

> 填写人和所在部门从 User.md 获取（`cordys.sh crm whoami` 的 userName / departmentName）。

## 步骤 3：输出卡片

- `success: true` → 用返回的 `link` 输出公司打卡卡片
- `success: false` → 提示"打卡系统暂时不可用，请稍后再试"

**公司打卡卡片**：`{时间段问候}，打卡卡片来了。` 卡片 JSON 模板见 `references/checkin-api.md`。

## Webhook 回调

收到打卡系统的 webhook 通知时，原样发送给用户（纯文本，不用卡片/markdown），不暴露技术细节。详见 `references/checkin-api.md` 的 Webhook 回调章节。

失败通知：`打卡失败，请重新说"打卡"再试。`
