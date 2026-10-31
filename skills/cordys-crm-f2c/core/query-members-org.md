# 👥 成员、人名与部门范围

凡涉及"具体人"（有没有叫 X 的、X 是谁、按人名查、分配派单、改 owner）或"部门/团队"范围的查询，先读本文件。两个入口分工明确：

| 目的 | 入口 | 说明 |
|------|------|------|
| 查人、取 userId、成员名单 | `crm members` | 服务端按姓名过滤；部门范围由 CLI 自动递归展开 |
| CRM 业务记录（线索/商机/合同…）的部门条件 | `crm org ids [部门名称或ID]` | 返回本部门 + 全部子孙部门 ID 数组，写入 `departmentId` 条件 |
| 按部 → 组 → 团队汇总 | `crm org outline [部门名称或ID]` | 返回 `id/name/parentId/path/depth` 层级 |
| 接口诊断 | `crm org tree` | 后端原始树；普通分析用 ids/outline 的稳定输出 |

范围词（我的 / 我的团队 / 全公司）如何落到 SELF、owner 或部门，以 `core/role-engine.md` §2.4 为准，本文件只负责"拿到正确的 ID"。

---

## 1. 人名 → userId（唯一入口）

```
crm members --name <姓名>
   → 服务端按 userName CONTAINS 过滤，直接返回匹配记录，取 userId 字段（不是 id）
   → owner 过滤写 {"operator":"IN","name":"owner","value":["<userId>"],"multipleValue":false,"type":"MEMBER"}
```

- `--name` 在未指定部门时自动补全公司部门范围（带缓存）。已知对方父部门时可加 `'{"departmentIds":["<父部门ID>"]}'`，CLI 自动包含子孙部门。
- 用户说"我的"时直接取 Cordys.md 的 userId，不必查 members。
- `crm page member`、`crm search user`、`crm fuzzy user`、`crm page org`、`raw .../member/*` 均不存在；遇到空结果用 `crm members --name` 重试。
- 真·查无此人的信号：`--name` 返回 `{"list":[],"total":0}` 且 code 100200。公司里有此人（含停用账号）就一定会被命中。
- `code=100200` 是成功终态：直接解析 stdout，不得重跑同一请求，不得写 `/tmp`、合并 stderr、正则抠 JSON 或另起 Python 二次解析。无 JSON/非 100200 时只按原始错误报错，不得伪装成空名单。
- `owner` ≠ `follower`：`owner` 是负责人（记录归属），`follower` 是跟进人。"我的线索/客户/商机"按 `owner`（或 `viewId:SELF`）；`follower` 用于写跟进记录的场景。

## 2. 在职过滤（status）按场景决定，默认不加

无脑追加在职过滤会把停用账号挡在结果外，导致按人名找人时误答"查无此人"（停用账号 `enable=false` 仍在册）。

| 场景 | 行为 |
|------|------|
| 按人名找人 / 取 userId | **不加** status |
| 明确要"在职/活跃成员名单""派单候选人" | `crm members ... --active`；CLI 注入 `status=true` 条件并核验每条 `enable=true` |
| 用户主动指定状态（"禁用的""离职的"） | 用用户指定的值 |
| 用户给的完整 JSON 已有 `status` 条件 | 原样保留 |

`status` 是请求条件，`enable` 是响应字段。顶层 `"enable":true`、顶层 `"status":true` 均无效并会被 CLI 在联网前拒绝；`--active` 与自定义 status 条件冲突时同样拒绝。

## 3. 部门范围：部门是树，范围必须含子孙部门

"销售一部有多少人 / 多少商机"问的是销售一部**体系内**的全部，不是一级。只有用户明确说"只看直属 / 不要子部门"才例外。

### 3.1 成员名单（`crm members`）

```bash
# 一条命令：父部门 ID 放顶层复数 departmentIds，CLI 读一次组织树展开、去重，再只 POST /user/list 一次
cordys.sh crm members '{"departmentIds":["销售一部ID","销售二部ID","销售三部ID"]}' --active --compact

# 只看直属成员时才加
cordys.sh crm members '{"departmentIds":["销售一部ID"]}' --active --compact --exact-departments
```

- `departmentIds` 必须是 payload **顶层复数数组**。后端只精确匹配所给部门、不递归；顶层单数 `departmentId` 会被静默忽略并把范围放大。CLI 分别用默认递归和联网前校验兜住这两种风险。
- `--compact` 只保留 `userName/userId/departmentId/departmentName/enable` 和 `total`；compact 的 `departmentId` 与 `crm org outline` 的 `id` 直接关联。
- 多个部门汇总：把多个父部门 ID 放进同一个数组。多个部门分别统计：一次查全部父部门，再按 outline 的 `parentId` 归属。
- 不要因父部门原始查询人数少而手工 `org ids` 后重跑；默认命令已经完成同一递归。

### 3.2 CRM 业务记录的部门条件（`crm org ids`）

```
1. Cordys.md「部门范围」已有数组（经理初始化时写入）且用户说的是"我部门/我的团队" → 直接使用，不调接口
2. 用户指定了其他部门名，或缓存缺失 → cordys.sh crm org ids <部门名称或ID>
   ├─ 名称精确匹配优先；唯一的包含匹配也可用
   └─ 同名或模糊命中多个部门时命令会报歧义，改用候选中的部门 ID
3. 把 stdout 的完整 JSON 数组原样放进 departmentId 条件
```

标准模式（值必须是数组，即使只有一个 ID；键名是 `name` 不是 `field`；type 固定 `TREE_SELECT`）：

```json
{"value": ["dept_a", "dept_b", "dept_c"], "operator": "IN", "name": "departmentId", "multipleValue": false, "type": "TREE_SELECT"}
```

| 场景 | 行为 |
|------|------|
| "我部门"、经理未指定范围 | 用 Cordys.md 部门范围（已含子部门） |
| 指定具体部门名（"销售一部"） | `crm org ids` 定位并展开 |
| 多个部门的业务记录分别统计（"一部、二部商机各多少"） | 每个部门**分别**展开，构造各自的条件 |
| "全公司 / 全部" | 仅 profile 允许全公司时不加部门过滤并用 `ALL`；销售角色拒绝扩大 |
| 部门没有子部门 | 数组只含该部门自己的 ID |

### 3.3 层级汇总（`crm org outline`）

`crm org ids` 的扁平数组顺序**不表示父子关系**。需要按"部 → 组 → 团队"汇总时，另执行一次共同上级范围的 `crm org outline <部门>`，按成员响应或记录的 `departmentId` 连接 outline 的 `id`，再沿 `parentId` 归入目标层级。指定目标时目标节点 `depth=0,parentId=null`，子孙使用相对层级。不得凭名称、输出顺序或"组/团队"字样猜父节点。

## 4. 端点速查

| 端点 | 方法 | 对应 CLI | 约束 |
|------|------|---------|------|
| `/department/tree` | GET | `crm org tree/ids/outline`；`crm members` 默认内部调用 | 当前账号可见组织树 |
| `/user/list` | POST | `crm members` | 顶层 `departmentIds` 只精确匹配，不含子部门；CLI 默认先展开 |
