# 接口问题与排查记录

> 本文档记录 Cordys CRM 技能包在对接后端接口 / CLI 时踩过的坑，用于后续追溯。
> **遇到新的接口问题，按下方模板追加一条，不要删旧条目。** 每条包含：现象、根因、正确做法、已做的修复。
> 排查口径同步沉淀到 `skills/core/cli-spec.md` 等运行时文档，本文档只做"问题账本"。

模板：

```
## YYYY/MM/DD —— 一句话标题
- 现象：
- 根因：
- 正确做法：
- 修复：（改了哪些文件 / 是否需重新打包部署）
```

---

## 2026/06/24 —— 查用户 userId 反复翻车（`crm page <任意词>` 静默返回空）

- **现象**：要把线索"分配给万梓良"，模型反复查不到这个用户，连试 `crm page member`、`crm fuzzy user`、`raw POST /member/query/all`、`raw POST /org/members`、`raw GET /member/list` 等十余种命令，全部返回空，最终判定"系统里没这人"。实际系统里有：万梓良 → userId `1131998760411284`，部门=苏皖线下团队。
- **根因**：
  1. **静默空返回陷阱**：`cordys.sh` 的 `crm_page` 对 module 名零校验，`crm page member` 会 POST 到不存在的 `/member/page`，后端**不报错、返回空**。模型把"空"理解成"查无此人"，于是不停换端点猜，进入死循环。
  2. 查用户的**唯一正确入口是 `crm members`**（打 `/user/list`），且该接口**只返回所传 `departmentIds` 里的成员**——之前会话只挑了顶层部门，漏掉万梓良所在的子部门。
  3. 文档诱导：§4.3 模块表把 `成员→members` 和 `lead→page,get,search` 并排，模型类推"member 也能 page"；§4.2 旧标题"按人名查数据"，模型接到"分配给某人"没对上号。
- **正确做法**（查任何"人"的 userId 唯一路径）：
  ```bash
  # 1. 取全公司全部部门 ID（不传参 = 全公司，含所有子部门）
  cordys_ext.sh dept-children
  # 2. 完整数组塞进 departmentIds + 带 keyword，接口端过滤
  cordys.sh crm members '{"departmentIds":[<上一步全部ID>],"keyword":"万梓良","pageSize":500}'
  # → 取返回里的 userId（不是 id）
  ```
  其他相关：`crm members` 不带 `departmentIds`（或空数组）会直接 NPE 报错 `getDepartmentIds() is null`；members 每条同时有 `id` 和 `userId`，过滤必须用 `userId`。
- **修复**：
  1. `skills/scripts/cordys.sh`：`crm_page` / `crm_search` 加 guard，遇到 `member/members/user/users/staff/employee/personnel/org/...` 等词**直接 die 报错并指路** `crm members` / `crm org`（见 §4.2），不再静默返回空。
  2. `skills/core/cli-spec.md`：§4.2 标题改"把人名解析成 userId（查数据/分配/改负责人通用）"并扩展触发场景；禁令清单列全试过的假命令；§4.3 模块表 members/org 行标注"只有 crm members/crm org，不支持 page/search"。
  3. 已同步到部署目录 `.workbuddy/skills/cordys-crm/`，并重新打包 `cordys-crm.zip`。

## 2026/06/24 —— `pool assign` 假成功（多传 poolId 参数错位）

- **现象**：执行 `pool assign lead <clueId> <poolId> <userId>`，返回 `code:100200` 看似成功，实际未分配。
- **根因**：`assign` 只接受 2 个参数 `<id> <assignUserId>`，**不需要 poolId**。多传的 poolId 被当成 assignUserId，真正的 userId 被丢弃，后端收到错误归属却仍回 100200。
- **正确做法**：`pool pick <id> <poolId>`（领取需 poolId）、`pool assign <id> <userId>`（分配不需要 poolId），两者第 2 个参数完全不同。
- **修复**：`cordys_ext.sh` 的 pick/assign/batch-* 加参数个数校验，多传立即 die 报错；`write-flow.md` 加 pick vs assign 参数对比 ⚠️ 框。

## 2026/06/24 —— SELECT 字段查询填中文静默返回空

- **现象**：按"行业=银行"等 SELECT 条件查询，部分选项填中文返回空。
- **根因**：SELECT/RADIO 字段**创建时传中文标签，查询条件 `combineSearch.conditions` 的 value 需传选项 ID**（当 label≠value 时）；填中文会静默返回空。
- **正确做法**：查 `references/forms/{module}.md` 的「SELECT 字段可选值」段，标注「查询用 ID」的字段按 `=` 右侧 ID 填；未标注的中文即 ID。
- **修复**：`tools/sync_forms.py`（MaxKB 服务端源码）输出 SELECT 字段时带上选项 ID 映射；cli-spec §5.2 加规则，§8 空结果重试加例外（SELECT 填中文是假空，换 ID 重试一次）。

## 2026/06/24 —— `account.md` 表单同步永远不更新

- **现象**：跑 `cordys_ext.sh sync`，account.md 始终不刷新，行业等字段拿不到 ID。
- **根因**：`tools/sync_forms.py` 的 `MODULE_TO_REF` 把 `account→customer`，sync 输出 `customer.md.snippet`，但仓库文件叫 `account.md`，target 不存在，snippet 被丢弃。
- **正确做法**：映射应为 `account→account`。
- **修复**：改 `MODULE_TO_REF` 映射；该文件是 MaxKB 服务端源码，**改后需更新到 MaxKB 并重跑 sync**。

## 2026/06/24 —— `cordys_ext.sh` 所有写操作随 asker=null 静默崩溃（exit 1 无输出）

- **现象**：`cordys_ext.sh check '{...}'` 等命令返回 exit 1 且**完全无输出**，看不出原因。bash -x 显示卡在取 asker 的那行。
- **根因**：`_call_remote` 第 73 行 `asker=$(... | grep -o '"userName": *"[^"]*"' ...)` 期望 `/personal/center/info` 返回带引号的 `userName`。但部分账号（如本测试用的 Administrator）该接口返回 `"userName":null`，grep 匹配不到带引号串 → **grep 退出 1**，叠加脚本顶部 `set -eo nounset` + `set -o pipefail`，整条赋值语句失败，脚本在调 MaxKB 之前就静默退出 1。asker 只是个可选上下文名，却把全链路带崩。`_call_remote` 是 check/create/follow/transform/form/sync 的公共函数，**所有写操作都受影响**，不止 check。chat_id 提取行同样裸露（取不到本应由下方 die 报错，却会先被 set -e 静默带崩）。
- **正确做法**：可选提取的管道末尾加 `|| true`，失败留空而非中断；必需值（chat_id）取不到交给紧跟的 `die` 守卫显式报错。
- **修复**：`skills/scripts/cordys_ext.sh` 的 asker、chat_id 两行各加 `|| true`。已同步部署目录并重新打包 `cordys-crm.zip`。（注：这是脚本侧 bug，非 MaxKB 服务端源码 `tools/*.py`，无需更新 MaxKB。）

## 2026/06/24 —— check 入参用错（`keyword` + 产品简称未转换）【模型行为，非接口 bug】

- **现象**：用户问"查一下赛摩智能 MK"，模型实际执行 `check '{"keyword":"赛摩智能"}'`——① 用了不存在的 `keyword` 字段；② 把"MK"整个丢了，未识别为产品。
- **根因**：模型没按 SOP 构造入参。check 入参 schema 是 `{"客户名":...,"手机":...,"产品":[...]}`，无 `keyword`；"MK"应按 `references/mappings/product-alias.md` 转成"MaxKB 专业版"放入 `产品`。规则在 `sop/duplicate-check.md` 和 `profiles/sales.md` 都有，是模型未遵循，非文档缺失。
- **正确做法**：`check '{"客户名":"赛摩智能","产品":["MaxKB 专业版"]}'`。
- **修复**：文档规则已齐备（duplicate-check.md「意图识别」列表 + sales.md「查重参数构建」），无需改文档。属运行时遵循问题，记此条供追溯。

## 2026/06/25 —— `crm page/search` 管道喂 JSON（`@-`/`-`）被当 keyword 静默返回空

- **现象**：模型用 `echo '<JSON>' | cordys.sh crm page opportunity @-`（JSON 经 stdin 管道）查询，`total` 返回 0，误判"成单 0 单"。同条件直接 inline 传 JSON 则正常返回 13。
- **根因**：`crm_page`/`crm_search` 只把「以 `{` 开头」的实参当 JSON，其余走 `page_payload` 当 **keyword**。`@-` 不以 `{` 开头 → 被当成 `keyword="@-"` 去搜 → 搜不到 → `total=0`。`aggregate` 早就支持 `-` 读 stdin，page/search 却不支持，行为不一致诱导踩坑。（另注：page 经 `merge_payload` 已兜底 `current:1`，inline JSON 不会缺 current；缺 current 报 `code:100400 当前页码必须大于0, data:null`，会被 `.get('data',{})` 读成空——这是模型自己拼 JSON 漏 current 的另一路径，非脚本 bug。）
- **正确做法**：要么 inline 传 `crm page opportunity '{...}'`；要么用 `@-`/`-` 管道（修复后已支持）。
- **修复**：`skills/scripts/cordys.sh` 的 `crm_page`、`crm_search` 在分支判断前加 stdin 识别：`first` 为 `-` 或 `@-` 时 `first=$(cat)` 从标准输入读 JSON（与 aggregate 一致）。已实测 `@- → total=13`。脚本侧改动，重新打包 zip，无需更新 MaxKB。

## 2026/06/25 —— 经理团队查询 `departmentId` IN 模板写成单字符串，后端报 not iterable

- **现象**：模型按 `profiles/sales-manager.md` 团队查询模板填 `departmentId` 条件，反复报 `Return value (...) was not iterable`，填单个 ID 字符串也报，被迫去读 `cordys.sh` 源码、自己用 Python 拼原生数组才跑通（一次查询空转 5 步）。
- **根因**：模板把 `operator:"IN"` 的 value 写成单字符串占位符 `"value":"{departmentId}"`。IN 操作符要求 value 是**数组**，后端拿到字符串 → 试图迭代 → `not iterable`。`dept-children` 本就返回 ID 数组，模板却按单值写，且 `multipleValue:false`。
- **正确做法**：`{"value":["<deptId1>","<deptId2>"],"operator":"IN","name":"departmentId","multipleValue":true,"type":"TREE_SELECT"}`，value 填真数组、不带引号；只查一个部门也写单元素数组 `["<id>"]`。实测带数组 `code=100200, total=13`。
- **修复**：`skills/profiles/sales-manager.md` 6 处模板 value 改为数组占位符 `{departmentId}`（不带引号）、`multipleValue:true`；模板表上方加 ⚠️ 说明强调"是 JSON 数组、必须真数组"。文档改动，重新打包 zip。

## 2026/06/25 —— 测试时 `.env` 覆盖命令行 env，打错租户得"假数据"【测试操作坑】

- **现象**：用 A 租户（`crm.fit2cloud.com`）的 key 在命令行传入跑 `cordys.sh crm aggregate`，却稳定返回与 A 不符的结果（7 条/38.5，真值 13 条/494750），一度误判 aggregate 有 bug。
- **根因**：`cordys.sh` 第 14-18 行 `source .env` 发生在命令行 env 注入**之后**，`.env` 里的 `CORDYS_CRM_DOMAIN/ACCESS_KEY/SECRET_KEY` 覆盖了命令行传入值。skills 目录下的 `.env` 指向 B 租户 `cordys-demo.fit2cloud.cn`，于是实际打到 B 租户的数据集。
- **正确做法**：要临时用另一套凭证测试，先把 `.env` 移开（`mv .env .env.bak` … 测完还原），或直接改 `.env`。不能靠命令行 env 覆盖 `.env`。
- **修复**：无需改脚本（source .env 是预期行为）。记此条提醒排查时先确认 `.env` 指向哪个租户，避免把"打错库"误判成接口/逻辑 bug。另：`cordys.sh` 硬编码的 `curl --noproxy '*'` 在某些环境（本机 DNS 被代理接管、解析到保留段 198.18.x.x）会导致 DNS 解析失败、连不上；该环境下需走系统代理。

## 2026/06/25 —— `crm aggregate` 在某些环境静默查全租户（payload 经临时文件丢失）

- **现象**：经理查"销售三部六月成单"，`crm page` 正确返回 `total=13`，但**同条件** `crm aggregate opportunity amount sum` 返回 `count=25346 / value≈19.8 亿`——量级是全租户所有商机。aggregate 把过滤条件整个丢了，却返回一个貌似合理的巨大数字（最危险的"假成功"）。
- **根因**：旧实现里 page 与 aggregate 传 payload 走**两条不同路径**：page 把 JSON 作为命令行实参直接交 `merge_payload`（可靠）；aggregate 却先 `mktemp /tmp/cordys_agg_XXX.json` 写文件，再把 `/tmp/...` 路径经 env 传给 Windows 原生 Python，让它 `os.path.exists` 找回来。`/tmp` 是 Git Bash 的 MSYS 虚拟路径，经 env 传递时**是否转换成 `C:\...\Temp\` 取决于环境的启发式规则**——某些环境（如模型运行的 workbuddy）不转换，Python 拿到原始 `/tmp/...` → `os.path.exists` 为 False → payload 退化成空 `{}` → 第 77 行补空 `conditions` → 查全租户求和。**且失败时不报错，静默用空条件查全库**。实测：不传 payload 时 aggregate count=25347，与模型看到的 25346 吻合，坐实。
- **正确做法**：payload 不经文件、直接通过环境变量传内容；并区分"用户没传 payload（合法，查全库）"与"传了 payload 但读/解析失败（必须报错中止，绝不静默查全库）"。
- **修复**：`skills/scripts/cordys.sh` 的 `crm_aggregate` 重写：① 用 `CORDYS_AGG_PAYLOAD` 传 payload **内容**（不再用临时文件 + `CORDYS_AGG_PAYLOAD_FILE`），消除 MSYS 路径转换隐患；② 新增 `CORDYS_AGG_HAS_PAYLOAD` 标记，传了 payload 但内容为空或非法 JSON 时打印 error 到 stderr 并 `exit 1`，**不再静默查全库**；③ 顺带支持 `@-` stdin。实测：inline/`@-` 均返回正确 13/494750；非法 JSON → exit 1、stdout 空；不传 payload → 正常全库（合法用法）。脚本侧改动，重新打包 zip，无需更新 MaxKB。

## 2026/06/25 —— DYNAMICS 自定义天数 `["CUSTOM",90,"BEFORE_DAY"]` 是坏格式，后端报 ClassCastException

- **现象**：查"销售三部超过3个月没跟进的线索"，模型按文档（`cli-reference.md`、`crm-api.md`、旧版 `cli-spec.md` §5.4）写 `{"value":["CUSTOM",90,"BEFORE_DAY"],"operator":"DYNAMICS","name":"followTime","type":"TIME_RANGE_PICKER"}`，后端 `code:100500` 报 `ClassCastException: class java.util.ArrayList cannot be cast to class java.lang.String`。模型遂放弃精确查询，改用"按 followTime 排序翻两页肉眼看分布"来估，方法不可靠（只看了 60/192 条，且不含从未跟进的 null）。
- **根因**：① 文档错。后端 DYNAMICS 的 value **只接受字符串常量**（TODAY/WEEK/MONTH/LAST_THIRTY…），传数组直接 ClassCast。**根本没有"自定义天数"的 DYNAMICS 写法**，文档那行是错的。② 语义缺口：模型未把"从未跟进"（followTime 为 null）计入"超过N天没跟进"。
- **正确做法**：自定义天数（常量表没有的，如 90 天）→ AI 算出"N天前"北京时间毫秒戳 `tsN`，用 `LT` + 标量 `tsN` + `DATE_TIME`（等价 `BETWEEN [0, tsN]`）。`LT`/`BETWEEN` 不含 null，"超过N天没跟进"业务上应 `LT(tsN) + EMPTY(followTime)` 两次查询相加。计数用各条件 `total` 相加，勿靠排序翻页肉眼估。实测（crm.fit2cloud.com 销售三部）：总 192 = EMPTY(0)+NOT_EMPTY(192)，LT-30天(0)+GE-30天(192)，自洽；LT-90天=0，故"超过3个月没跟进=0"。
- **修复**：`skills/core/cli-spec.md` §5.4 删除错误的 `["CUSTOM",90,"BEFORE_DAY"]` 行，改为 ⚠️ 警告（DYNAMICS 只收字符串常量、传数组报 ClassCast）+ "早于N天/N天未更新"的正确算法（LT+毫秒戳+DATE_TIME，含 EMPTY 语义补全）。**官方文件 `cli-reference.md:172`、`references/crm-api.md:138` 同样写了坏格式，经用户同意一并改正为正确算法**；运行时权威规则在 cli-spec §5.4。脚本无改动，重新打包 zip。
