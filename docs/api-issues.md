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

## 2026/07/10 —— 线索转化存在两个公开入口：裸端点成功但静默丢失商机字段

- **现象**：文档和 `cordys.sh` 同时公开 `crm transform/transition` 与 `cordys_ext.sh transform`。调用前者时接口可返回 `code:100200`，但金额、结束日期、签约类型和自定义 `moduleFields` 未写入新商机，形成“转化成功”的空壳记录。
- **根因**：`/lead/transform` 与 `/lead/transition/account` 只完成基础转化，不负责转换后的联系人、客户和商机字段补全；完整流程需要转化后定位新记录，再执行 update。该多步事务仅在 `scripts/sop/transform_lead.py`（由 `cordys_ext.sh transform` 调用）实现，但旧文档和基础 CLI 仍把裸端点当成可选入口。
- **正确做法**：线索转化只能执行 `scripts/cordys_ext.sh transform '<JSON>'`，一次传入全部中文字段；不得执行 `cordys.sh crm transform/transition`，也不得通过 `cordys.sh raw POST /lead/transform` 或 `/lead/transition/account` 绕过。
- **修复**：统一 `SKILL.md`、`core/cli-spec.md`、`core/write-engine.md`、`core/cli-reference.md`、`core/linkage-engine.md` 为唯一入口；从 `cordys.sh`/`cordys.py` 移除裸转化实现和 help 示例，对旧 `crm transform/transition` 及 raw 转化端点改为明确拒绝并指向 `cordys_ext.sh transform`；新增离线契约测试。仅修改开发仓库，尚未同步部署目录或重打包。

## 2026/07/09 —— 并行 follow + follow-plan 双双 exit 1 空输出：被写入前的 auto-sync 静默拖垮

- **现象**：并行跑 `cordys_ext.sh follow` 和 `follow-plan`，两条**完全相同地** exit 1、stdout/stderr 皆空，跟进记录/计划都没写进去（写入调用根本没执行）。单独顺序跑通常没事，并行才复现。
- **根因**：
  1. `cmd_follow`/`cmd_follow_plan` 的**第一行都是 `_auto_sync`**，真正的写入在其之后。失败点在两者共享的前置步（auto-sync），不是各自的写入 payload——所以两条现象一模一样。
  2. `_auto_sync` 内 `cmd_sync >/dev/null 2>&1 && _mark_synced`：并行时两进程同时看到过期 stamp，**各自触发一次 `cmd_sync`**。sync 会原地重写 `references/*.md`、读写 `*.snippet`，两个 sync 撞同一批文件（一个 `rm -f` 删掉另一个正 `cat` 的 snippet、`> "$target"` 边写边被 `sed` 读），管道里某步失败。
  3. `set -eo pipefail` 下 `cmd_sync` 返回非 0 → `&&` 短路 → `_auto_sync` 作为裸命令行返回非 0 → **`set -e` 直接中止整个脚本**，且输出早被 `>/dev/null 2>&1` 吞掉 → exit 1 + 双空。
  4. `_py_sop_json`（07/09 上一条修的空输出防护）只包住 Python 写入路径，**完全没覆盖 auto-sync 这个前置步**，给了"写入路径已安全"的假象。
- **正确做法**：**写入命令一律串行**——一条返回后再发下一条，绝不 `&` 并行、绝不同批同时发起多条写入（即使互相独立，如"同时建跟进记录+跟进计划"）。查询无副作用，可照常并行。这是调用方（模型）的调度纪律，不靠脚本加锁兜。
- **修复**（改 repo，需用户同步部署目录 + 重打包）：
  1. **写入串行写进运行时文档**：`core/write-engine.md` 新增 §0.5「写入命令一律串行，禁止并行」，列明约束范围（create/update/batch-update/transform/follow/follow-plan/pool）与"查询可并行"的边界，让模型遵守。
  2. **`_auto_sync` 永不 fatal**（`cordys_ext.sh`）：改为 `_needs_sync || return 0`；`if cmd_sync …; then _mark_synced; fi`；末尾 `return 0`。这样单次 sync 失败（API 超时等，串行下也会发生）不会经 `set -e` 静默杀掉写入。
  - 曾试过在 `cmd_sync` 加 `mkdir` 原子锁串行化 sync，但（a）等待锁反而让并行写入卡住数十秒，（b）在脚本层兜并发本属过度设计——已回退，改用上面的"调用方串行"纪律。
  - 注：本例死在写入前，未产生幽灵数据；但按 §3 规矩重试/排查后仍应 `crm page` 查证一次。

## 2026/07/09 —— cordys_ext follow 静默 exit 1 空输出；绕过脚本泄露密钥；whoami 超时拖垮 follow-plan

- **现象**：最优链路 search 成功后，`scripts/cordys_ext.sh follow/follow-plan` 在 WorkBuddy 下 exit 1、stdout/stderr 皆空，平台仍可能显示「运行成功」。模型改用 `python -c` 直调 sop 并在命令行导出 ACCESS/SECRET。follow-plan 曾因 `/personal/center/info` 超时失败，补传 owner userId 后成功。
- **根因**：
  1. `set -e` + `result=$(python -c ...)`：Python 非 0 退出时命令替换失败，脚本在 `echo "$result"` 之前退出；stderr 未并入替换，表现为**完全静默**。
  2. 模型违反「不得绕过脚本」：直调 Python 并把密钥写进命令行（安全事故）。
  3. `resolve_owner` 缺省必调 whoami；`/personal/center/info` 超时则整单失败。已是 userId 时仍会先 get_me。
- **正确做法**：只跑 `bash scripts/cordys_ext.sh follow|follow-plan '…'`；密钥只在 `.env`；失败看输出中的 `error` 或「Python 工具无输出」提示。owner 可省略或传数字 userId。
- **修复**：`cordys_ext.sh` 增加 `_py_sop_json`（stderr 合并、异常 JSON、空输出 die；Python 仍靠 PATH/`CORDYS_PYTHON`/`py -3`）；follow/follow-plan 改走该包装。`add_follow_record.py`/`add_follow_plan.py`：userId 短路不 whoami、whoami 失败不阻断、timeout 20s。visit-flow/SKILL 禁止密钥进命令行与假成功。需同步部署目录。

## 2026/07/08 —— 跟进计划新增 add 端点：字段名反直觉、与跟进记录多处不同

- **现象**：新增"跟进计划录入"能力时，摸 `/follow/plan/add` 入参踩了两层坑：① 按表单 `/follow/plan/module/form` 暴露的 `planType`/`planClue`/`planStartTime`/`planMethod`/`planContent`（planXxx internalKey）传，报 `type must not be blank / method must not be blank`；② 参照跟进记录用 `followTime`/`followMethod`，`followTime` 被静默忽略、时间没写进去。
- **根因**：
  1. **add 端点不吃表单的 planXxx 键，只认存储态字段名**：`type`/`clueId`/`content`/`estimatedTime`/`method`。表单的 `internalKey`（planXxx）只是展示层，其 `businessKey` 才是存储名（planType→type、planStartTime→estimatedTime、planMethod→method、planContent→content）。这与其它模块"表单字段即写入字段"的习惯相反。
  2. **跟进计划 vs 跟进记录字段名不同**：计划时间是 `estimatedTime`（记录是 `followTime`），计划方式是 `method`（记录是 `followMethod`）；且**计划必填 `type`+`method`，记录只必填 `type`**。
  3. **两者跟进方式选项 ID 不是同一套**：计划表单 微信=`176776378282600000`、邮件=`176092554492700000`、线上会议=`175375488829300000`；记录表单 微信=`176776376843300000`、邮件=`176092552150400000`、线上会议=`175375487193300000`。混用会写错方式。
  4. **端点有两个版本**：全局 `/follow/plan/add` 和 module 前缀 `/{module}/follow/plan/add` 都能写（实测均 100200），与记录保持一致用 module 前缀版。
  5. **查询侧 `/follow/plan/page` 的 `sourceId`/`clueId`/`keyword` 过滤基本不生效**（传了仍返全量），定位单条得靠 `myPlan:true`+排序自己找——只影响回查验证，非写入问题。
- **正确做法**：走 `cordys_ext.sh follow-plan '<JSON>'`（新增），端点 `/{module}/follow/plan/add`，存储字段名 `type`(CLUE/CUSTOMER)+对应 ID(clueId/customerId/opportunityId)+`content`+`estimatedTime`(毫秒)+`method`(计划表单的选项 ID)。方式选项每次从 `/follow/plan/module/form` 取，不复用记录表单。
- **修复**（均改 repo，分支 `ext`）：新建 `scripts/sop/add_follow_plan.py`（镜像 add_follow_record.py，改端点/method/estimatedTime/读计划表单）；`cordys_ext.sh` 加 `follow-plan` 子命令 + `cmd_form` 的 follow-plan case + help；`sync_forms.py` 加 `follow-plan` 映射（FORM_PATH_MAP/MODULE_TO_REF/默认 modules），`gen_follow_snippet` 的方式选项过滤放宽到 `businessKey in (followMethod, method)`、触发条件放宽到 `m in (follow, follow-plan)`；新建 `references/forms/follow-plan.md`（AUTO 区块 sync 生成 + 手写写入补充，含与记录的字段差异表）；SKILL.md/cli-spec.md/write-engine.md(§6.5)/profiles/sales.md/crm-api.md 同步补 follow-plan。实测（crm.fit2cloud.com，大众燃气线索 398984062159048704）：中文"微信"→176776378282600000、"2026-07-20 14:30"→1784529000000，`code:100200`、status=PREPARED。打包部署由用户执行。

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

## 2026/06/26 —— cordys_ext.sh 本地化后 Python 调用全挂（MSYS 路径 + cp936 编码）

- **现象**：把 `tools/*.py` 从 MaxKB 远程调用改为 `cordys_ext.sh` 本地直调（删 `_call_remote`）后，所有写入命令（check/create/follow/transform/sync）报 `ModuleNotFoundError: No module named 'check_duplicate'`；改对路径后，输出的中文又全是乱码（`线索`→`����`）。
- **根因**：两个独立的 Git Bash × 原生 Windows Python 坑（与 2026/06/25 aggregate 的 `/tmp` MSYS 路径同源）：
  1. **路径**：`SCRIPT_DIR` 在 Git Bash 下是 MSYS 路径 `/c/Users/.../scripts`，把它 `os.path.join(..., 'tools')` 交给**原生 Windows Python** → 拼成 `/c/...\tools`（反斜杠拼接），Python 不认 `/c/` 前缀，`os.path.isdir` 为 False → import 失败。中途还踩过 heredoc(`<<'PY'`) 下 `__file__` 未定义、以及"传 .py 路径 + heredoc"导致 heredoc 内容被当文件参数吞掉的弯路。
  2. **编码**：原生 Windows Python **忽略 `LANG`/`LC_ALL`**，stdout 默认按系统代码页 cp936 编码，中文输出乱码。
- **正确做法**：① 路径用 `cygpath -m` 把 MSYS 路径转成混合路径 `C:/...`（Linux/macOS 无 cygpath 时原样用），经 `CORDYS_TOOLS_DIR` 环境变量传给 Python，脚本里 `sys.path.insert(0, os.environ['CORDYS_TOOLS_DIR'])`；② 脚本顶部 `export PYTHONUTF8=1` + `PYTHONIOENCODING=utf-8` 强制 UTF-8 I/O（Linux/macOS 无副作用）；③ Python 调用统一用 `-c` 内联代码（不用 heredoc，避免 `__file__`/参数吞噬问题）。
- **修复**：`skills/scripts/cordys_ext.sh`：顶部加 `PYTHONUTF8`/`PYTHONIOENCODING` 导出 + `CORDYS_TOOLS_DIR`（cygpath 转换）导出；5 个工具调用（check/create/follow/transform/sync）改为 `-c` 内联 + 读 `CORDYS_TOOLS_DIR`。实测 5 命令 + update(heredoc 纯 stdlib)+dept-children(95 部门) 全通过，中文 UTF-8 正确。已同步部署目录 `.workbuddy/skills/cordys-crm/`（含新增 `scripts/tools/`）并重新打包 `cordys-crm.zip`（46 文件）。**注：tools/*.py 本地化后不再需要更新 MaxKB，但 zip 内已含 tools，部署方式有变，需告知用户。**

## 2026/07/01 —— `cordys_ext.sh sync` 写回 AUTO 区块失效（生成正确但没落盘）

- **现象**：改了 `sync_forms.py` 让产品带 ID 后跑 `cordys_ext.sh sync`，显示"同步完成"、`git status` 也显示 forms/*.md 被改（M），但 **AUTO-GENERATED 区块内的内容（产品行、说明块等）没有任何变化**（git diff 只看到区块外手写段的旧改动）。直接调 `sync_forms.py` 函数，输出内容完全正确（产品行带全 ID、说明块是新的）。
- **根因**：`sync_forms.py`（生成）是对的；坏在 `cordys_ext.sh` 的 `cmd_sync`（约 §700-730）**写回环节**——它把 Python 输出按 `===FILE:references/...===` 标记切成 `.snippet`、再用 sed 提取 `AUTO-GENERATED-START/END` 之间做替换。marker 无 CRLF、`.snippet` 无残留（替换分支确实跑了），但 AUTO 区块内容未被更新。疑似 `while IFS= read <<< "$content"` 分段或 sed 区间替换在某环节丢了数据（未定位到具体行，待深挖）。
- **正确做法**：sync 生成逻辑（sync_forms.py）可信；写回逻辑不可信时，**手动用生成内容更新目标行**（用 `sync_forms()` 输出取行 → 正则替换 forms/*.md 的对应整行）。
- **修复**：本次未修 `cmd_sync` 写回 bug（记账待修）。产品 ID 用脚本直接调 `sync_forms()` 取产品行、正则整行替换进 4 个 forms（lead/opportunity/contract/payment-record 的「产品类型（可多选）」行，contact 无产品字段）。`sync_forms.py` 生成侧改动（产品保留 `name=id`、说明块改「创建走 cordys.sh 传 ID」）已就绪，待 `cmd_sync` 写回修好后可完整自动化。**待办：定位并修复 `cmd_sync` 的 AUTO 区块写回。**

  - **【2026/07/01 已修】根因找到**：原生 Windows Python 的 `print()` 把 `\n` 转成 `\r\n`（text mode），`sync_forms.py` 输出经 bash `$()` 捕获后**每行尾都带 `\r`**。`cmd_sync` 用 glob 精确匹配 `===FILE:references/*.md===` 切分文件段——FILE 行实际是 `...lead.md===\r`，结尾是 `\r` 不是 `=`，**glob 匹配 0 次** → `.snippet` 不生成 → AUTO 区块永不更新（但 `find *.snippet` 无残留、显示"同步完成"，假象成功）。与 cp936/路径同属 Windows Python 坑。**修复**：`cmd_sync` 捕获 content 后加 `content="${content//$'\r'/}"` 去掉所有 `\r`。实测：跑 `cordys_ext.sh sync` 后 6 个 forms 的 AUTO 区块正常刷新、产品行带 ID、`.snippet` 正常清理。sync 恢复全自动。

## 2026/07/01 —— `cordys.sh crm update` 全量覆盖 moduleFields（只传一个字段清空其余）

- **现象**：用 `cordys.sh crm update account '{"id":"...","moduleFields":[{"fieldId":"1751888184000005","fieldValue":"制造"}]}'` 只改行业，返回 `code:100200` 成功，但查回发现**区域/客户来源/类型/省市全被清空**，moduleFields 只剩行业一个。
- **根因**：`/{module}/update` 端点是**全量覆盖 moduleFields**——body 里没带的自定义字段一律清空。`cordys.sh crm update`（裸端点）把 body 原样 POST，没有"读回现有字段再合并"的步骤。对比：`cordys_ext.sh update`（create_entity 系）第 168-179 行**先取现有记录、继承现有 moduleFields、再合并新值**，专门防这个坑；`transform_lead.py` 更新客户/商机时也同样先读回合并。裸端点缺了这一步。
- **正确做法**：update 前**必须先 `cordys.sh crm page <module>` 查回现有全部 moduleFields，把要改的字段合并进去，整体提交**（顶层业务字段同理）。或直接用 `cordys_ext.sh update`（内置读回合并）。
- **修复**：本次按"裸端 + 文档强约束"处理——`core/write-engine.md §3` 重写更新流程，加"步骤2 查回现有全部字段 → 步骤3 合并 → 提交全量 moduleFields"，配 ✅/❌ 对照示例 + 🔴 全量覆盖警告；`cli-reference.md §5.3`、`cli-spec.md`、`SKILL.md`、`profiles/sales.md` 的 update 速查同步加警示。**注：此方案安全性依赖 LLM 每次先查回，漏一次即清字段；更稳的做法是把"读回合并"做进 `crm_update` 脚本内部（同 transform_lead.py），待定。**

## 2026/07/01 —— `cordys.sh crm update` 剥离 owner，更新时清空负责人

- **现象**：`cordys.sh crm update opportunity '{...改结束日期...}'` 第一次更新后商机 owner 丢失/归属异常，加 `CORDYS_KEEP_OWNER=1` + 显式 `owner` 重试才对（用户实际操作里 update 了两次就是这原因）。
- **根因**：`crm_update` 走 `write_payload`，而 `write_payload` **默认剥离 owner**（那是给 create 设计的——创建不传 owner 让后端设当前用户，避免 id/userId 坑）。但 update 是**全量覆盖**，剥掉 owner 等于把记录负责人清空。同一个 `write_payload` 服务 create 和 update，而两者对 owner 的正确行为**相反**（create 该剥、update 该留）。
- **正确做法**：update 保留 owner。
- **修复**：`scripts/cordys.sh` 的 `crm_update` 内部改为 `CORDYS_KEEP_OWNER=1 write_payload ...`，不再剥 owner；用户无需再手动加环境变量。`write-engine.md §0.3` 和 §3 owner 说明同步更新（创建剥/更新留，改负责人直接传 owner=userId）。这是脚本层确定性根治（区别于上一条 moduleFields 全量覆盖只能靠文档约束）。

## 2026/07/01 —— `crm_update` 改为脚本内读回合并（根治全量覆盖 + 去掉 KEEP_OWNER）

- **现象**：延续上两条。商机更新后「结束日期」`expectedEndTime` 丢失。此前 moduleFields 全量覆盖靠文档约束（LLM 先查全再传）、owner 靠硬加 `CORDYS_KEEP_OWNER=1`——都是"打地鼠"：`expectedEndTime` 是顶层系统字段，既不在 moduleFields 文档约束覆盖范围、也没像 owner 那样单独 KEEP，于是又被清。
- **根因**：`/{module}/update` 全量覆盖顶层可写字段 + moduleFields，body 没带的一律清空。逐字段打补丁补不完。
- **正确做法**：`crm_update` 内部先 GET 现有记录、把调用方字段覆盖上去再整体提交（同 `transform_lead.py`/`create_entity.py` 的读回合并思路），LLM 只传 id + 要改的字段。
- **回环格式验证**（拉 `crm.fit2cloud.com` 实测，商机 405712557924978697「华星-MK-2026-订阅新购」，用户名下）：
  - GET 详情的 `moduleFields` 形状就是 `{fieldId,fieldValue}`，与 update 入参一致 ✓
  - SELECT 字段返回的是**存储 value 不是 label**（如「来源」返 `二期及续费`，正是选项 value，label 另为「多期续费…」），回填即正确 ✓
  - `owner` 返 userId、日期返毫秒时间戳（存储原形），回填 update 接受 ✓
  - 恒等回环（GET→白名单 body 原样发→再 GET）：9 个 moduleFields + 顶层字段零丢失、零变更、`code:100200`；未回发的派生字段（`departmentId`/`stage`）也**自动保留**——证明 update 只覆盖它管的可写字段，不误伤派生字段
  - 端到端（极简 payload `{"id":...,"amount":314159}`）：amount 变更生效，`expectedEndTime`/owner/customerId/9 个 moduleFields 全保留 → 原 bug 修复。测后已还原 amount=300000
- **修复**：
  1. `scripts/cordys.sh` 新增 `merge_update_payload`（GET 现有记录 → DENY 掉只读/展示/审计/派生字段 → 归一 moduleFields → 用调用方值覆盖 → 落盘）；`crm_update` 改为「提取 id → GET → merge → api_write POST update」。LLM 只传 id + 要改字段，其余自动保全。
  2. **去掉 `CORDYS_KEEP_OWNER` 环境变量**（很别扭，用环境变量给 `write_payload` 传"create 还是 update"模式）：`write_payload` 改回纯 UTF-8 落盘，是否剥 owner 由显式位置参数决定——`crm_add` 传 `strip`（create 剥 owner 交后端），`crm_update`/`batch_update`/`transition`/`transform` 不传（保留 owner，且 update 已走读回合并自然保全）。
  3. 运行时文档同步：`write-engine.md §3` 重写为"只传要改的字段，脚本自动读回合并"（删掉 🔴 全量覆盖警告和"先查回全部字段"步骤）；`cli-reference.md §5.3`、`cli-spec.md`、`SKILL.md`、`profiles/sales.md` 的 update 速查同步改。
  - **DENY 名单**（不回发的字段）当前按商机字段实测确定，含 `*Name`/`createTime`/`updateTime`/`optionMap`/`attachmentMap`/`stage`/`stageName`/`inCustomerPool`/`departmentId`/`organizationId` 等。lead/account/contact 机制相同但尚未逐一实测，若某模块有未列入 DENY 的展示字段导致 update 报错，补进名单即可。

## 2026/07/03 —— 省市推断错误：`loc 上海市` 查不到 + inference-rules.md 没被读

- **现象**：创建上海的线索时，模型执行 `cordys_ext.sh loc "上海市"` 查省市代码，返回"未找到"；且整个创建流程未读 `sop/inference-rules.md`，省市推断错误。
- **根因**：
  1. **主因（加载指令不对等）**：`write-engine.md §0.2` 硬性要求「创建/更新前**必须先读** `references/forms/{module}.md`」，但对 `sop/inference-rules.md` 只在 profile 第 1 步软引用「应用…自动补充」，核心流程图的"推断"步骤也没绑定文件。模型读完 forms 就凭常识推断，跳过了 inference-rules，导致省市直辖市规则（只在该文档 §省市格式 定义）没生效。
  2. **直接现象（数据结构）**：`location_codes.json`（439 条）里直辖市**只有区级键、没有市级键**——普通省是三级（浙江省=33→杭州市=3301），直辖市只有 黄浦区=310101…浦东新区=310115，没有"上海市"也没有"上海=31"。所以 `loc 上海市` 子串匹配不到，必然返回"未找到"。正确应按区名查（`loc 浦东新区` → `310115-`），这条规则 inference-rules §省市格式 本就写对了，只是没被读到。
- **正确做法**：创建/更新前必须同时读 forms/{module}.md 和 sop/inference-rules.md；直辖市省市代码按区名查，未指定区用默认区（北京→朝阳区110105、上海→浦东新区310115、天津→滨海新区120116、重庆→渝北区500112）。
- **修复**：
  1. `skills/cordys-crm/core/write-engine.md`：§0.2 标题改「先懂表单 + 推断规则」，把 `sop/inference-rules.md` 提升为与 forms 同级的**强制前置**（含省市格式说明）；核心流程图"读表单定义"步骤补「+读推断规则(inference-rules)」。
  2. `skills/cordys-crm/scripts/cordys_ext.sh`：`cmd_loc` 加直辖市 guard——传 上海/北京/天津/重庆（含带"市"）时不返回干巴巴的"未找到"，而是指路到区名并给默认区代码。已实测 `loc 上海市` 触发提示、`loc 浦东新区`→`310115-`，4 个默认区码均在库中。
  3. 仅改 repo；部署与打包由用户执行。

## 2026/07/03 —— 赢单分析链路又长又错：误用 actualEndTime + BETWEEN 传字符串

- **现象**：查"销售三部 2026 上半年赢单商机分析"，模型连跑 10 条命令（crm org → dept-children → page 三次试错 → aggregate 两次 → dist 两次），且结果偏低不对。
- **根因**：
  1. **结果不对（字段错）**：最终用 `actualEndTime` 做时间过滤。该字段本库大量为空，`BETWEEN` 不含 null 记录（cli-spec §5.4），漏掉大批赢单 → 少算。正确字段是 `expectedEndTime`（文档本就明令"actualEndTime 不用于统计"）。
  2. **跑偏的起点（格式错被误判成字段错）**：第一次其实字段选对了（expectedEndTime），但 `BETWEEN` 传了字符串日期 `"2026-01-01 00:00:00"` 而非毫秒时间戳，查不到；模型误判是字段问题，改用了它凭直觉认为对的 actualEndTime，越走越偏。
  3. **链路冗余**：`crm org` 与 `dept-children` 重复（后者已内含取树）；aggregate 跑两次（--by 那次已含合计）；dist 跑两次且已过滤 stage=SUCCESS 后再按 stage 分布无意义。
- **正确做法**（赢单分析标准三步，见 profiles/sales-manager.md）：
  1. `dept-children "<部门>"` 拿 ID；
  2. `crm aggregate opportunity amount sum '{departmentId IN + stage=SUCCESS + expectedEndTime BETWEEN [毫秒戳,毫秒戳]}' --by ownerName` —— 一条出总额+排名+单数+合计；
  3. 要明细才补 `crm page`。时间字段用 expectedEndTime，BETWEEN 传毫秒戳。
- **修复**（文档本身没错，是加固模型行为，均改 repo）：
  1. `core/cli-spec.md §5.4`：actualEndTime 验证表行补"为什么禁用"（大量为空、BETWEEN 漏 null、会少算）；决策顺序后加"排错纪律"——时间查询结果异常先查是不是传了字符串日期，别因结果不对就换字段。
  2. `profiles/sales-manager.md`：新增「赢单分析——标准三步配方」块，含三条铁律（用 expectedEndTime、BETWEEN 传毫秒戳、aggregate --by 一条到位不要再 dist）。
  3. 仅改 repo；部署与打包由用户执行。

## 2026/07/03 —— 查跟进记录链路又长：`crm page follow` 静默返回空（未 guard）

- **现象**：查"销售三部本周跟进记录"，模型先 `crm page follow`（空）→ `crm search follow keyword=销售三部`（空）→ 读 follow.md → raw `/follow/record/page`（失败）→ 才改查 opportunity/account 的 followTime，共 6+ 条，且漏了 lead。
- **根因**：
  1. **follow 不是可 page 的顶层模块**：跟进记录只能按父模块查——`crm follow record <lead|account|opportunity>` POST 到 `/{module}/follow/record/page`（cordys.sh crm_follow_page 强制要 module）。没有独立 `/follow/page`、`/follow/record/page`（无 module 前缀）。
  2. **`crm page follow` / `crm search follow` 当时没被 guard 拦**（guard 只覆盖 member/user/org 那批），打到不存在的 `/follow/page` → 静默返回空 → 模型误判"没数据"，重蹈 2026/06/24 查用户那次的覆辙（静默空→反复猜端点）。
  3. **跟进记录无 departmentId 字段**（follow.md 查询字段表可证），没法按部门直接过滤团队跟进记录，模型只能绕去查业务模块的 followTime——这步方向对，但没有现成配方，且只查了 opp/account 漏了 lead。
- **正确做法**：
  - 口径 A（本周被跟进的业务记录+跟进人，最常用）：`crm page lead/account/opportunity` 三个都查，加 `followTime DYNAMICS WEEK` + `departmentId`，读 follower/owner 汇总。
  - 口径 B（跟进明细内容）：`crm follow record <module> '{...}'`，团队范围按 owner IN 成员userId 或 followTime 过滤（无 departmentId）。
- **修复**（均改 repo）：
  1. `skills/cordys-crm/scripts/cordys.sh`：crm_page/crm_pageall/crm_search 三处 guard 增加 `follow/follows/followup/follow-up/record/records`，die 并指路 `crm follow record <module>` 与口径 A。已实测 `crm page follow` 触发报错。
  2. `skills/cordys-crm/profiles/sales-manager.md`：新增「团队本周跟进情况」配方，讲清 A/B 两口径、别 page follow、lead 别漏、跟进记录无 departmentId。
  3. 仅改 repo；部署与打包由用户执行。

## 2026/07/03 —— profile 用了不存在的时间字段，签约/回款统计静默返 0

- **现象**：审核发现三个 profile 用了后端不存在的字段做时间过滤：sales.md「我的签约」用 `signTime`、finance.md「回款日报」用 `paymentTime`、contract-admin.md「本月签约/今日待签」用 `startTime`(口径错)。
- **实测确证**(PowerShell 直连后端，DYNAMICS YEAR)：
  - 合同：无过滤 total=10400；`createTime` today-year=1380(正常)；**`signTime`=0**(code 仍 100200)。
  - 回款：无过滤 total=13840；`recordEndTime`=1575(正常)；**`paymentTime`=0**(code 仍 100200)。
  - 即：字段名后端不认时，返回 `code=100200`(成功) + `total=0`，不报错——典型静默错数。用户问"今年签约多少"会得到"0 单"，实际 1380。
- **根因**：权威字段以 `references/forms/{module}.md` 的 sync 快照为准——contract 新签口径=`createTime`(contract.md:106)、回款主时间=`recordEndTime`(payment-record.md:9/38)。`signTime`/`paymentTime` 根本不在同步字段表里；`startTime` 存在但语义是"合同开始时间"≠签约时间。
- **正确做法**：签约/新签统计一律 `createTime`，回款统计一律 `recordEndTime`；构造合同/回款时间过滤前核对 forms 字段表，别凭直觉用 signTime/paymentTime。
- **修复**(均改 repo)：sales.md `signTime`→`createTime`；finance.md `paymentTime`→`recordEndTime`；contract-admin.md 本月签约/今日待签 `startTime`→`createTime`(保留 startTime 作为"合同开始时间"字段定义)；并附口径注释。
- **附**：本次实测暴露沙箱环境 curl 报 `getaddrinfo() thread failed to start`(解析线程起不来)，ping 通、PowerShell 走 .NET DNS 可用——后续在本机做联网验证优先用 PowerShell Invoke-RestMethod，不要纠结 python。

## 2026/07/10 —— follow 查询封装回归：接收 module 却仍调用无 module 前缀端点

- **现象**：严格审查发现 `cordys.sh crm follow record|plan <module> ...` 虽强制传父模块，但 `crm_follow_page` 实际请求仍是 `/follow/{kind}/page`；`cordys.py` 备用实现同样如此。该路径与 2026/07/03 已确认的正确链路冲突，可能 HTTP 200 + 空内容并被误判为“没有跟进记录”。
- **根因**：Shell/Python 函数签名加入了 `module` 参数，guard 和运行时文档也改成 `/{module}/follow/{plan|record}/page`，但最终 URL 拼接漏用了 `module`；`references/crm-api.md` 表格与 raw 示例还残留无前缀旧端点，形成代码/文档双向漂移。
- **正确做法**：查询跟进必须 POST `/{module}/follow/{plan|record}/page`，module 常用 `lead`、`account`、`opportunity`；`sourceId` 必须取该父模块的业务主键。无 module 前缀返回空不能作为无数据证据。
- **修复**：本次仅审查、尚未改运行代码；应将 `scripts/cordys.sh` 改为 `${crm_base}/${module}/follow/${kind}/page`，同步修改 `scripts/cordys.py` 与 `references/crm-api.md:70-71,157-158`，增加 URL 契约测试后重新同步部署并打包。当前属于发版阻断项。

## 2026/07/10 —— follow 查询 module 前缀修复完成

- **现象**：同上条，Shell/Python 查询封装接收 `module`，实际 URL 却遗漏父模块前缀。
- **根因**：函数签名、guard 和文档先完成迁移，最终 URL 拼接及 API 表格/示例没有同步迁移。
- **正确做法**：统一执行 `cordys.sh crm follow <plan|record> <lead|account|opportunity> '<JSON>'`，请求必须落到 `/{module}/follow/{plan|record}/page`。
- **修复**：`cordys.sh` 与 `cordys.py` 均将 `module` 拼入 URL；`references/crm-api.md` 表格和示例、`sync_forms.py` 注释同步修正；新增 `tests/test_follow_query_url.py`，覆盖三种模块、Shell URL 字面契约和文档残留检查。仅修改开发仓库，未同步 WorkBuddy，未打包。
