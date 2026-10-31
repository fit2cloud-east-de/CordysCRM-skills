# 🧠 角色感知引擎

本文件定义 AI 如何读取已获取的 Cordys 用户身份并匹配到五个内置工作模式。身份获取、角色匹配和 `Cordys.md` 写入均由 AI 按本文步骤显式完成，不依赖后台任务或目录扫描器。

---

## 1. 初始化流程

每次对话开始（或 API Key 变更后），执行：

```
检查 Cordys.md 是否存在？
├─ 存在 → 验证有效性（非空、含 userId 与角色ID、记录时间未超过 7 天）
│   ├─ 有效 → 加载角色上下文，进入交互
│   └─ 无效 → 重新执行初始化
└─ 不存在 →
    ├─ cordys.sh crm verify                 验证 API Key
    ├─ cordys.sh crm whoami                 获取用户信息 (GET /personal/center/info)
    ├─ 匹配角色（§2）
    ├─ 角色为 sales-manager 时：cordys.sh crm org ids <departmentId>   展开本部门及全部子部门
    ├─ 将结果写入 Cordys.md                 持久化身份、部门和部门范围（§3）
    └─ 加载 profiles/{role}.md
```

**为什么初始化就展开部门范围**：经理的默认查询范围是"本部门及子部门"，几乎每次团队查询都要用到这组 ID。初始化时展开一次写进缓存，后续查询直接取用，不必每轮重复调用 `crm org ids`。其他角色不需要部门范围（销售只查本人，高管/财务/商务是全公司），不展开。

**换账号 / 刷新身份**：用户说"刷新身份"或"换账号" → 重新执行上述流程，覆盖 Cordys.md。用户说"组织架构变了"或部门条件查询明显缺人时，也重新展开部门范围。

> `Cordys.md` 位于 skill 根目录，由 AI 按本文维护，请勿手动编辑。

---

## 2. 角色匹配规则

采用**两层匹配策略**：先尝试用户自定义映射，再 fallback 内置规则。

### 2.1 用户自定义角色映射（优先级最高）

如果 `.env` 中配置了 `ROLE_MAP` 环境变量，则优先使用：

```bash
# .env 配置示例
# 格式：岗位关键词|岗位关键词...=角色ID，多组只用英文逗号分隔
# 角色ID 只能是 sales、sales-manager、finance、executive、contract-admin

ROLE_MAP=总经理|副总裁|VP=executive,总监|经理|销售运营专员|销售经理|销售主管=sales-manager,商务|合同管理=contract-admin,销售|顾问=sales,财务|会计|出纳=finance
```

AI 在启动时读取 `ROLE_MAP`，解析为映射表：

```python
# AI 内部解析逻辑（参考）
import os

ROLE_MAP = {}
raw = os.environ.get("ROLE_MAP", "")
allowed_roles = {"sales", "sales-manager", "finance", "executive", "contract-admin"}

for entry in raw.split(","):
    entry = entry.strip()
    if "=" not in entry:
        continue
    keywords, role_id = entry.rsplit("=", 1)
    role_id = role_id.strip()
    if role_id not in allowed_roles:
        continue
    for kw in keywords.split("|"):
        if kw.strip():
            ROLE_MAP[kw.strip()] = role_id

# 匹配流程
def match_custom(positions, role_map):
    """按自定义映射匹配：返回第一个匹配的角色ID"""
    for kw in sorted(role_map.keys(), key=len, reverse=True):  # 长关键词优先
        if any(kw in pos for pos in positions):
            return role_map[kw]
    return None
```

> **为什么长关键词优先？** 比如同时有"经理"和"区域经理"，长关键词更精确。如果不追求层级可以省略排序。

### 2.2 内置角色映射（fallback）

当 `ROLE_MAP` 未设置或无匹配时，使用内置规则。**顺序很重要**：领域词（财务、商务）必须排在通用管理词（经理、总监）之前，否则"财务经理""商务总监"会被"经理/总监"截获成销售经理，拿到与其职责不符的部门数据范围。

```python
fields = response.data
position = str(fields.position or "")

# 优先级 1：管理员（id=admin 或角色包含 admin）
if fields.id == "admin" or "admin" in str(fields.roles or ""):
    role = "sales-manager"  # 管理员默认按经理视角

# 优先级 2：高管岗（全公司视角，不限制部门）
elif any(kw in position for kw in
         ["总经理","副总裁","VP","CEO","COO","CFO","总裁","合伙人","董事长"]):
    role = "executive"

# 优先级 3：财务岗（领域词优先；"财务经理/财务总监"归财务）
elif any(kw in position for kw in ["财务","会计","出纳"]):
    role = "finance"

# 优先级 4：商务/合同岗（领域词优先；"商务经理/商务总监"归商务）
elif any(kw in position for kw in ["商务","合同管理","合同专员","法务","合规"]):
    role = "contract-admin"

# 优先级 5：带"经理"字样的一线销售岗（客户经理是销售岗位名，不是管理岗）
elif any(kw in position for kw in ["客户经理","大客户经理"]):
    role = "sales"

# 优先级 6：管理岗（部门视角）
elif any(kw in position for kw in
         ["经理","总监","主管","负责人","leader","部长","主任"]):
    role = "sales-manager"

# 优先级 7：销售岗
elif any(kw in position for kw in
         ["销售","BD","专员","顾问","业务员","运营"]):
    role = "sales"

# 兜底：无法识别时默认个人模式（防止权限扩散）
else:
    role = "sales"
```

> **注意**：自定义映射优先于内置规则。如果 `ROLE_MAP` 中写了某个关键词，即使内置规则有不同映射，也以自定义为准。
> **代码实现**：`scripts/sop/quote_context.py` 的 `match_role` 按 §2.1–2.3 实现同一套规则，供 `crm quote-context` 在 `Cordys.md` 缺失或过期时使用；修改本节规则时同步修改该函数。
> **匹配规则说明**：高管岗优先于一切管理岗，避免"总经理"被普通经理规则截获；财务、商务从管理岗和销售岗独立出来；"客户经理"按最小权限归销售，若贵司的客户经理确实带团队，用 `ROLE_MAP` 显式映射到 `sales-manager`。

### 2.3 无法识别时的确定性兜底

`position` 为空、`ROLE_MAP` 未命中或配置了非法角色 ID 时，固定使用 `sales`。不根据历史对话、常查模块或用户临时措辞推断更高权限角色。

### 2.4 角色与本次查询范围分离（强制，全技能唯一权威）

角色只决定**权限上限**和用户未指定范围时的**默认范围**；用户原话决定本次查询范围，二者分开处理。其他文档（query-engine、cli-spec、profiles、visit-flow 等）只引用本节，不另行改写。

| 用户语义 | 查询范围 |
|---|---|
| "我的 / 我负责的 / 我名下的 / 归我的"业务记录；"我有哪些 / 我有多少"线索、客户、商机等 | 在 profile 允许该模块的前提下使用模块 `viewId:SELF`；无 SELF 时用 `owner=当前用户 userId`；不加部门条件，不展开部门 |
| "我的团队 / 我的部门 / 我的下属 / 我们部门 / 团队 / 部门" | 组织范围：经理使用本部门及全部子部门（Cordys.md 的部门范围），不得误判为 SELF |
| 明确指定某成员 | 在角色授权范围内使用该成员 `owner=userId`（先按 `crm members --name` 解析） |
| "全部 / 所有人 / 全公司" | 只在 profile 允许全公司时生效；销售角色拒绝扩大，保持 SELF/owner 并说明范围 |
| 未出现本人、具体人、团队/部门或公司范围 | 应用当前角色的默认范围 |

- 范围优先级：权限边界 → 用户明确指定的本人/具体人/团队/公司范围 → 当前角色默认范围。
- 经理有权查看部门，不等于每次都查部门。例如经理问"我有哪些超过 7 天没跟进的线索"，`latestFollowUpTime` 的 `LT` 与 `EMPTY` 两次查询都必须使用 `viewId:"SELF"`，不能改写成 `viewId:"ALL" + departmentId`，也不要为这类查询调用部门展开。
- 任何用户措辞都不能越权；角色默认值也不能扩大用户明确指定的较小范围。
- 自定义视图可以缩小查询口径，不能扩大当前 profile 的强制范围；必要时继续叠加 SELF、owner 或部门条件。

---

## 3. Cordys.md 生命周期

### 创建

```markdown
# 🧠 用户身份上下文

> 自动获取：2026-05-09 10:30
> 匹配角色：sales-manager

## 身份信息
| 字段 | 值 |
|------|-----|
| 用户ID（userId） | admin |
| 姓名 | 张三 |
| 岗位 | 销售一部经理 |
| 邮箱 | zhang@company.com |
| 部门ID | 1131998760411000 |
| 部门名称 | 销售一部 |
| 角色ID | sales-manager |

## 部门范围
<!-- 仅 sales-manager 写入；crm org ids <部门ID> 的完整 stdout 原样保留，顺序不表示层级 -->
["1131998760411000","1131998760411001","1131998760411002"]
```

- `用户ID` 取 whoami 响应的 `userId`（不是成员记录的 `id`），后续 `owner` 条件和 `{userId}` 占位都用它。
- `部门ID`/`部门名称` 取 whoami 响应的 `departmentId`/`departmentName`；响应没有这两个字段时留空，经理范围退回运行时调用 `crm org ids`。
- `部门范围` 只对 sales-manager 写入，内容是 `crm org ids <部门ID>` 的完整 JSON 数组。它是查询范围，不是层级；需要按部/组汇总时另用 `crm org outline`。

### 刷新条件

| 事件 | 动作 |
|------|------|
| 用户说"刷新身份" | 重新执行初始化 |
| 用户说"换账号" | 清除 Cordys.md + 重新初始化 |
| 用户说"组织架构变了"，或部门条件查询明显缺人 | 只重新执行 `crm org ids` 并更新「部门范围」 |
| 连续 3 次 API 调用返回 401/403 | 提示用户检查密钥，建议刷新 |
| 文件记录时间超过 7 天 | 下次对话开始时重新执行初始化 |

### 约束

- `Cordys.md` 是运行时产物，**不提交版本控制**
- AI 每次对话第一件事：确认 Cordys.md 就绪且有效
- 如果 Cordys.md 存在但解析失败（格式损坏），视为不存在
- Cordys.md 中的值是可信缓存，直接使用，不要每轮调接口二次验证
