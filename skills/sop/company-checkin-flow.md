# 公司打卡流程

用户说"打卡""签到""上班""到公司"时执行本流程。不涉及 CRM，只创建打卡链接。

**轻量初始化**：本流程只需 Cordys.md（取姓名、部门），不用加载 `core/role-engine.md` 和 `profiles/{角色}.md`。Cordys.md 不存在时回退完整初始化。打卡完成后，如果用户后续消息涉及 CRM 操作，补加载角色引擎和角色配置。

---

## 步骤 1：企业微信判断

检查对话上下文中是否有 sender_id：

- **有** → 继续步骤 2
- **无** → 提示"请在企业微信中发起打卡"，结束

---

## 步骤 2：创建打卡链接

本步骤只创建打卡任务和临时 token，不写打卡记录表（用户点击卡片并完成定位后才写表，见步骤 4）。

```bash
bash scripts/checkin.sh create-checkin '{
    "userid": "<sender_id>",
    "填写人": "<Cordys.md 姓名>",
    "所在部门": "<Cordys.md 部门>",
    "打卡类型": "公司打卡",
    "用户类型": "企业微信用户"
  }'
```

> 请求/响应格式、卡片 JSON 模板、`.env` 自动读取（`CHECKIN_API_URL`/`OPENCLAW_WEBHOOK_URL`）详见 `references/checkin-api.md`。填写人/所在部门取自 `cordys.sh crm whoami` 的 userName / departmentName。

## 步骤 3：输出卡片

- `success: true` → 用返回的 `link` 输出公司打卡卡片
- `success: false` → 提示"打卡系统暂时不可用，请稍后再试"

**公司打卡卡片**：`{时间段问候}，打卡卡片来了。` 卡片 JSON 模板见 `references/checkin-api.md`。

## 步骤 4：用户点击卡片后写入打卡表

由打卡系统 H5 自动完成（`POST /api/wechat/submit-checkin`，凭 `userid + token + 经纬度` 读取暂存字段写表），skill 不手动调用。写表完成后打卡系统通过 `webhookUrl` 发回通知，转发由平台已有能力处理。

> 不在 skill 文档或对用户输出中暴露真实表名、表结构、内部字段名或连接信息，统一称"打卡记录表"。
