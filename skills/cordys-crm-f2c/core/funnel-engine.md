# 📊 L2C 漏斗分析引擎

本文件定义了如何利用 Cordys CRM 统计 API 进行 L2C 管道分析和漏斗计算。

---

## 1. 核心统计 API

### 1.1 首页统计

| 端点 | 用途 | 响应 |
|------|------|------|
| `POST /home/statistic/lead` | 线索统计 | 本年/本月/本周/本日的新增线索数 |
| `POST /home/statistic/opportunity` | 商机统计 | 本年/本月/本周/本日的商机数 + 金额 |
| `POST /home/statistic/opportunity/success` | 赢单统计 | 本年/本月/本周/本日的赢单商机数 + 金额 |
| `POST /home/statistic/opportunity/underway` | 进行中商机 | 本年/本月/本周/本日进行中的商机数 + 金额 |

**请求体**（`HomeStatisticBaseSearchRequest`）：

```json
{
  "searchType": "SELF",
  "deptIds": ["dept_id_1"],
  "timeField": "CREATE_TIME",
  "userField": "OWNER",
  "priorPeriodEnable": true
}
```

`timeField` 必须与业务事件一致：新增线索/新增商机用 `CREATE_TIME`；赢单/成交（`opportunity/success`）用 `EXPECTED_END_TIME`。首页 `opportunity/underway` 返回的是服务端预设时间桶，不等于“截至当前的完整开放管道”；完整管道需以 `stage NOT_IN [SUCCESS,FAIL]`（字段 type 仍为 `SELECT`）查询商机明细，再按返回记录本地统计数量和金额。业务字段以 `references/forms/opportunity.md` 为准。

**角色映射**：

| 角色 | searchType | deptIds |
|------|-----------|---------|
| 销售 | `SELF` | 空 |
| 经理 | `DEPARTMENT` | Cordys.md 中的 `{departmentId}`（展开子部门） |
| 高管 | `ALL` | 空 |
| 财务 | `ALL` | 空 |

### 1.2 模块统计

| 端点 | 用途 | 响应 |
|------|------|------|
| `POST /contract/statistic` | 合同统计 | `{amount, averageAmount}` |
| `POST /contract/payment-record/statistic` | 回款统计 | `{amount, averageAmount}` |
| `POST /opportunity/statistic` | 商机统计 | `{amount, averageAmount}` |
| `POST /order/statistic` | 订单统计 | `{amount, averageAmount}` |

**请求体**（`BaseCondition`）：

```json
{
  "viewId": "ALL",
  "combineSearch": {
    "searchMode": "AND",
    "conditions": [
      {"value": "MONTH", "operator": "DYNAMICS", "name": "recordEndTime", "type": "TIME_RANGE_PICKER"}
    ]
  }
}
```

上例是回款统计口径。不同模块必须使用各自业务时间：合同新签用 `contract.createTime`，实际回款用 `contract/payment-record.recordEndTime`。禁止给所有统计机械套 `createTime`；回款记录的 `createTime` 只是录入时间。

### 1.3 客户级统计

| 端点 | 响应 |
|------|------|
| `GET /account/contract/statistic/{accountId}` | `{totalAmount}` |
| `GET /account/contract/payment-plan/statistic/{accountId}` | `{totalPlanAmount}` |
| `GET /account/contract/payment-record/statistic/{accountId}` | `{totalAmount, receivedAmount, pendingAmount}` |
| `GET /account/invoice/statistic/{accountId}` | `{contractAmount, uninvoicedAmount, invoicedAmount}` |

### 1.4 合同级统计

| 端点 | 响应 |
|------|------|
| `GET /contract/invoice/statistic/{contractId}` | `{contractAmount, uninvoicedAmount, invoicedAmount}` |

---

## 2. 漏斗查询

### 2.1 销售视角

```bash
cordys.sh crm stat-home lead
cordys.sh crm stat-home opportunity
cordys.sh crm stat contract '{"viewId":"SELF","combineSearch":{"conditions":[{"value":"MONTH","operator":"DYNAMICS","name":"createTime","type":"TIME_RANGE_PICKER"}]}}'
```

### 2.2 经理视角

```bash
cordys.sh crm stat-home lead '{"searchType":"DEPARTMENT","deptIds":["id1","id2"],"timeField":"CREATE_TIME","userField":"OWNER","priorPeriodEnable":true}'
```

### 2.3 高管视角

```bash
cordys.sh crm stat-home lead '{"searchType":"ALL","timeField":"CREATE_TIME","userField":"OWNER","priorPeriodEnable":true}'
```

---

## 3. 漏斗输出格式

输出格式见 `core/output-engine.md` §9。

`HomeStatisticSearchResponse` 字段：

```json
{ "value": 45, "priorPeriodCompareRate": 0.18 }
```

→ 输出：`线索 45 条（📈 +18% vs 上期）`

---

## 4. 管道预测

```bash
# 全公司赢单金额（按预计结束时间口径）
cordys.sh crm stat-home opportunity/success '{"searchType":"ALL","timeField":"EXPECTED_END_TIME","userField":"OWNER"}'
```

开放管道命令已同时返回 `count` 和 `value`，禁止再执行 `crm page | python` 求和，也不得用临时文件搬运大 JSON。阶段分布单独使用 `crm dist opportunity stage`。

---

## 5. API 速查表

| 场景 | API |
|------|-----|
| 我的线索数 | `crm stat-home lead` |
| 部门线索数 | `crm stat-home lead '{"searchType":"DEPARTMENT",...}'` |
| 合同金额汇总 | `crm stat contract` |
| 回款汇总 | `crm stat contract/payment-record` + `recordEndTime` 时间条件 |
| 客户回款概览 | `crm acct-sub payment-record-stat {id}` |
| 客户开票概览 | `crm acct-sub invoice-stat {id}` |
| 截至当前商机管道数量/金额 | `crm page opportunity` + `stage NOT_IN [SUCCESS,FAIL]`，按返回明细本地统计 |
