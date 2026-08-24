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

## 2026/08/07 —— 单个表单接口失败导致整批同步回滚，并阻断后续查询/写入

- **现象**：全量表单同步时，只要一个模块的 `/module/form` 或 `/view/list` 请求失败，后续模块不再请求，已成功获取的模块也不会落盘；`sync-if-needed` 的非零退出码还会使查询或写入命令在真正业务请求前直接停止。
- **根因**：`sync_forms.py` 以全量文件/模块集合为原子校验单位，抓取循环没有模块级异常隔离，应用阶段也要求一次生成全部 forms/schema；`cordys.sh`、`cordys_ext.sh` 与备用 `cordys.py` 又把自动同步异常当成 fatal 前置条件。
- **正确做法**：每个模块是独立快照单元。某模块表单或视图同步失败时，记录警告并保留该模块最后有效的本地 Markdown/schema，继续获取和提交其他模块；自动同步整体异常也只告警，后续任务继续使用当前本地快照。只有目标本地表单本身缺失或无法解析、无法安全组装字段时才停止该项写入。
- **修复**：`scripts/sop/sync_forms.py` 改为逐模块容错、部分输出校验和 schema 合并提交，失败模块不覆盖；`cordys_ext.sh`、`cordys.sh`、`cordys.py` 的自动同步改为 fail-open；同步更新 `SKILL.md`、`core/cli-spec.md`、`core/query-engine.md`、`core/write-engine.md` 与 Agent 路由说明。需同步两个 WorkBuddy 运行副本并重打 1.2.5 包。

## 2026/07/10 —— `crm members` 输出链路被误判，单次查询演变为五次重跑

- **现象**：销售三部名单使用同一 `departmentIds` 连续执行 5 次，并反复写 `/tmp`、合并 stdout/stderr、正则提取 JSON；轨迹中出现 5 次 Python 解析和 14 次临时文件操作，查询链路明显变长。
- **根因**：普通 members 分支仍走“Python 生成临时 body → curl → command substitution → rm → echo”，而姓名分支是单进程 urllib；Windows Git Bash 的清理噪声混入执行轨迹后，AI 把成功输出误判为 stderr/乱码，开始盲目重放。旧实现还默认 `pageSize=30`，团队人数超过一页会漏人；部门缓存未按 CRM 实例和账号隔离。
- **正确做法**：统一通过成员专用单进程查询器；已有完整 `departmentIds` 时只 POST `/user/list` 一次，字段缺失时才读 6 小时隔离缓存或拉部门树，显式空数组必须失败关闭；默认 `pageSize=500` 且禁止 `viewId:ALL`。模型直接消费 `--compact` stdout，只有 `code=100200` 且响应结构合法才视为成功，禁止临时文件、正则抠 JSON和同条件重跑。
- **修复**：新增 `scripts/sop/members_query.py`，统一 `cordys.sh` 与备用 `cordys.py` 的 members 语法，新增 `--compact`、参数/响应校验和离线测试；同步更新 `core/cli-spec.md`、`profiles/sales-manager.md`，版本升至 1.4.1。需同步部署目录并按 git 跟踪文件重打包。

## 2026/07/10 —— 查询语义与 CLI 技术契约脱节，静默空结果或全库统计被当成正确数据

- **现象**：“本周复盘”会把 `WEEK` 机械加到存量指标；SELECT 用中文标签、错字段/错 type/operator、秒级时间戳可联网后静默返空；只显示“运行成功”时模型仍声称“数据齐了”；`aggregate/dist/pageall` 及父维度入口可绕过条件校验，签约后模块错传顶层 `customerId` 甚至会统计全库。
- **根因**：业务事件、时间字段和存量/流量判断仅散落在 forms/profile；CLI 没有共享可执行的字段契约，各入口自行解析 payload；表单 Markdown 可供 AI 阅读，但不适合运行时稳定校验。
- **正确做法**：查询先依用户原话区分当前存量与期间事件，再读对应 `references/forms/{module}.md` 确定字段/枚举/时间口径；CLI 在联网前用同一份 `field-schema.json` 校验字段、type、operator 和 value 形状；只以 stdout 真实响应为结论证据。
- **修复**：新增 `core/query-engine.md`、`references/field-schema.json`、`scripts/sop/query_contract.py`；将 page/search/stat/pageall/aggregate/dist、父维度查询和备用 Python CLI 接入契约；`sync` 同源全量生成 forms + schema 并原子替换；修复数字关键词、危险父 ID、未知模块、枚举、时间戳、空值、聚合/分布绕过及业务时间口径；增加离线回归测试。已同步 WorkBuddy 并重新打包。

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

## 2026/07/10 —— CRM Domain 缺失时静默回落固定公网域名

- **现象**：`CORDYS_CRM_DOMAIN` 在 Skill 元数据中声明必填，但 `cordys.sh`、`cordys_ext.sh`、`cordys.py` 缺失配置时均回落到 `https://www.cordys.cn`；只配置密钥而漏配 Domain 仍会向公网发请求。
- **根因**：三套 CLI 内置了同一默认地址，公共鉴权检查只校验 Access/Secret，没有把 Domain 视为发送密钥前的强制安全条件。
- **正确做法**：所有联网命令必须在发请求前验证 Domain 已显式配置，且只能是 `https://主机[:端口]` 根地址；拒绝 HTTP、路径、查询串、URL 凭证和非法端口。
- **修复**：删除三套 CLI 的公网默认值，在公共 `check_keys` 中统一校验并规范化尾部 `/`；SKILL 错误处理同步声明无 fallback；新增 `tests/test_crm_domain_validation.py` 覆盖默认值残留、Python 非法地址、合法 HTTPS 端口及两套 Shell 缺失 Domain 拦截。仅修改开发仓库，未同步 WorkBuddy，未打包。

## 2026/07/10 —— 销售角色可被“全部/所有人”措辞解除本人范围

- **现象**：`profiles/sales.md` 先声明销售只能查本人，后又规定用户说“全部/所有人”时去掉 owner；`cli-spec.md` 的通用“全部→ALL”规则也没有角色前置条件。
- **根因**：把用户查询意图的范围词放在角色权限约束之后执行，导致低权限 profile 可被普通措辞覆盖；部分销售 search 示例还遗漏 `viewId:SELF`。
- **正确做法**：角色 profile 的范围是最高优先级约束。销售查询 lead/account/opportunity 必须保持 SELF/当前 owner，contact 必须保持当前 owner；“全部/所有人/全公司/全部门/某同事”只能被拒绝，不能生成 ALL、部门或他人 owner 查询。
- **修复**：删除 sales 的去 owner 例外，修正销售搜索与 Customer 360 示例；SKILL、cli-spec 增加不可覆盖规则并限制通用 ALL 语义；新增 `tests/test_sales_scope.py` 防止例外和无 SELF 搜索示例回归。仅修改开发仓库，未同步 WorkBuddy，未打包。

## 2026/07/10 —— 枚举与成员条件错用 EQUALS/NOT_EQUALS，示例和 dist 会生成非法查询

- **现象**：销售经理、财务、高管、商务 profile 对 `stage`、`planStatus`、`approvalStatus` 等 SELECT 字段使用 `EQUALS/NOT_EQUALS`，销售本人示例对 MEMBER 类型 `owner` 使用 `EQUALS`；`crm dist` 内部也用 `EQUALS + SELECT` 逐桶查询，与 `core/cli-reference.md` 的操作符契约冲突。
- **根因**：模板和脚本沿用了文本字段的单值写法，没有按实际字段类型选择 operator；SELECT/RADIO/MEMBER/DEPARTMENT/DATA_SOURCE 等枚举类只接受 `IN/NOT_IN`，且 `value` 必须是数组。
- **正确做法**：枚举/成员条件统一使用 `IN` 或 `NOT_IN`，单值也写成单元素数组；构造条件前以 forms 的实际 type 和 `core/cli-reference.md` 操作符表为准。
- **修复**：修正 sales、sales-manager、finance、executive、contract-admin 示例及 cli-spec 的 dist 示例；`cordys.sh` 的 `crm dist` 内部改为 `IN + [value]`。仅修改开发仓库，未同步 WorkBuddy，未打包。

## 2026/07/10 —— 合同无全局搜索端点，profile 却使用 crm search contract

- **现象**：销售经理团队签约合同示例调用 `crm search contract`，但签约后家族没有 `/global/search/contract`，CLI 会拒绝该模块；照抄示例会报错或被误判为查无数据。
- **根因**：profile 把普通模块的 `/global/search/{module}` 能力错误扩展到了 contract，`references/crm-api.md` 也残留 `/search`、`/advanced/search` 等与实际 CLI 不一致的路径。
- **正确做法**：合同按名称或条件查询使用 `crm page contract '<JSON>'`；客户/线索/商机/联系人全局搜索使用 `/global/search/{module}`；签约后子资源优先按父 ID 使用 `acct-sub`/`contract-sub`。
- **修复**：销售经理合同示例改为 `crm page contract`，`references/crm-api.md` 统一为真实 `/global/search/...` 端点并明确签约后家族不支持全局搜索。仅修改开发仓库，未同步 WorkBuddy，未打包。

## 2026/07/10 —— 转化参数名与线上商机字段名不一致，未匹配校验阻断整批补全

- **现象**：`cordys_ext.sh transform` 返回 `partialSuccess:true`，提示「最终用户全称（工商可查）」未匹配；基础客户、联系人和商机已创建，但金额、结束日期、签约类型、有效合同额也没有写入。
- **根因**：运行时文档传入旧名称「最终用户全称（工商可查）」，线上 `/opportunity/module/form` 实际返回「最终用户工商全称」；`transform_lead.py` 只做精确名称匹配，并在发现任一未匹配字段后于 `/opportunity/update` 前整体返回。该严格阻断由提交 `24e0b9f0` 新增，旧测试又用旧名称模拟表单，未覆盖真实契约。
- **正确做法**：新调用统一传「最终用户工商全称」；脚本把旧名称规范化为兼容别名，其他未知字段仍保持阻断，避免静默丢失。
- **修复**：更新 `transform_lead.py`、转化文档、字段映射和表单手写说明；回归测试使用线上真实字段名，并同时覆盖新名称与旧别名。已同步 WorkBuddy 并重新打包 `cordys-crm.zip`。

## 2026/07/10 —— 跟进计划的字符串毫秒戳静默回退当前时间，成功后重建造成重复计划

- **现象**：`follow-plan` 传入 `"计划时间":"1784253600000"` 后返回 `code:100200`，但新计划的 `estimatedTime` 是命令执行时刻；模型随后改传日期字符串再次新增，形成一错一对两条计划。
- **根因**：`add_follow_plan.py` 只把字符串按日期格式解析；纯数字字符串解析失败后被 `isinstance(et, int)` 判定为假，静默回退 `time.time()`。同时流程没有强调 `/follow/plan/add` 只有新增语义，模型把首次成功后的字段异常当作可重试失败。
- **正确做法**：计划时间接受 `YYYY-MM-DD HH:MM`、JSON 整数毫秒戳或纯数字字符串毫秒戳；显式非法值必须在联网前报错，不能替换为当前时间。任何 `code:100200` 都表示已创建，禁止再次调用新增接口纠错，应先查证并取得用户确认。
- **修复**：前置严格解析并固定 `estimatedTime`，兼容字符串毫秒戳，拦截秒级/非法值；删除 `add_follow_plan.py` 对非成功响应的内部自动新增重试；更新 `SKILL.md`、`visit-flow.md`、`follow-plan.md`、`write-engine.md` 的防重规范，新增离线回归测试。已同步 WorkBuddy 并重新打包 `cordys-crm.zip`。

## 2026/07/10 —— 经理定位查询把 condition 的 name/type 猜错，首轮三模块全部失败

- **现象**：经理按部门搜索公司时，三条 `crm search` 都把条件写成 `{"field":"departmentId","type":"INPUT"...}`，后端报 `combineSearch.conditions[0].name must not be null`；改成 `name + TREE_SELECT` 后立即命中。
- **根因**：`visit-flow.md` 只写“经理合并 departmentId”，没有给完整经理模板；`cordys.sh` 又把错误 conditions 原样发给后端。历史文档对 `multipleValue` 还同时存在 true/false，增加了猜测空间。
- **正确做法**：部门条件统一为 `{"value":["<deptId>"],"operator":"IN","name":"departmentId","multipleValue":false,"type":"TREE_SELECT"}`；`IN` 的 value 始终是真数组。`multipleValue:false` 已由本次真实成功查询验证，IN 的多值语义由 value 数组决定。
- **修复**：`cordys.sh` 的 `merge_payload` 为 `crm search` 增加联网前规范化/校验：无歧义时 `field→name`，冲突或非法条件直接报错；departmentId 强制 `TREE_SELECT + IN + 非空数组` 并规范化 `multipleValue:false`。`visit-flow.md` 增加经理三模块完整模板，sales-manager/cli-spec 同步统一，新增离线 Shell 集成回归测试。已同步 WorkBuddy 并重新打包 `cordys-crm.zip`。

## 2026/07/12 —— WorkBuddy 禁用 MSYS 路径转换，`sync` 把合法 JSON schema 误报为无效

- **现象**：`cordys_ext.sh sync-if-needed` 返回 `exit 1` 且 stdout/stderr 均为空；直接执行 `cordys_ext.sh sync` 才显示“同步生成的 JSON schema 无效，保留旧文件未覆盖”。三次失败后正式 forms 和旧 `field-schema.json` 均未覆盖、`.last_sync` 未生成，但 8 个 `forms/*.md.snippet` 各累积了三份相同内容。
- **根因**：WorkBuddy 沙箱为 Git Bash 设置 `MSYS_NO_PATHCONV=1` 和 `MSYS2_ARG_CONV_EXCL=*`，同时 `cordys_ext.sh` 选中原生 Windows Python。`cmd_sync` 把 Git Bash 的 `/c/Users/.../field-schema.json.snippet` 直接作为参数传给 `python -m json.tool`；路径不会转换为 Windows 格式，Python 实际报 `FileNotFoundError`。脚本又将校验器 stderr 丢到 `/dev/null`，并把任何非零退出都统一包装成“JSON schema 无效”，形成误导。失败分支只删 JSON snippet，而 Markdown 分段使用固定文件名和 `>>`，使每次重试继续追加残留。现场恢复出的三份 JSON snippet 均为 53,463 字节、SHA-256 相同，`json.loads`/`json.tool` 均能解析且包含完整 8 模块，排除 Cordys 表单数据或 `sync_forms.py` 生成非法 JSON。
- **正确做法**：让 Bash 打开输入文件，例如 `python -m json.tool < "$snippet_file" > "$json_tmp"`，避免把 MSYS 路径交给原生 Python；或先用 `cygpath -m` 转换所有传给 Python 的路径。校验 stderr 必须保留，并区分 JSON 解析失败与校验器/文件路径执行失败。整次同步应使用独立 staging 目录，全部校验通过后再统一原子替换，失败时清理本轮全部临时文件。调用侧只要同步失败就必须停止写入，不得以历史 forms“够用”为由继续。
- **修复**：先完成根因确认与运行时失败关闭规则；随后在 1.4.2 根治同步实现：`cordys_ext.sh` 不再用 Shell 固定 `*.snippet` 分片或把 MSYS 路径传给 `json.tool`，改为单个原生 Python 进程调用 `sync_forms()` 后直接交给 `apply_sync_output()`；写回器对固定 9 个目标做 allowlist、完整性、AUTO marker、精确 8 模块与 JSON 预校验，使用同卷独立 staging、进程锁、备份、`os.replace` 和失败逆序回滚，成功后才写 `.last_sync`，并保留真实异常。新增本地 Shell/原子性回归测试，覆盖禁用 MSYS 路径转换、含空格路径、旧 snippet、连续幂等、坏 JSON、普通异常与 `KeyboardInterrupt` 中断回滚，以及 OR-list 调用下失败退出码传播；全套 103 tests + 29 subtests 通过。已在 WorkBuddy 等效 MSYS 环境连续执行两次真实同步，9 个目标字节稳定、无临时残留，并重新打包。

## 2026/07/12 —— 修复已部署到用户技能目录，但 WorkBuddy 实际调用工作区内的 1.4.0 旧副本

- **现象**：修复版在 `C:\Users\wzl_n\.workbuddy\skills\cordys-crm-f2c` 连续同步成功后，模型仍从 `C:\Users\wzl_n\WorkBuddy\main\cordys-crm-f2c` 执行并再次报告同一个“JSON schema 无效”；该目录同时产生 8 个 Markdown snippet 残留。
- **根因**：机器上同时存在两份可执行技能。此前只同步了用户技能目录，但本轮命令明确调用工作区本地副本；后者仍是 1.4.0，保留 `python -m json.tool "$snippet_file"` 和固定 snippet 追加逻辑。修复本身没有复发，而是没有部署到实际执行路径。
- **正确做法**：遇到已修复错误复现时，先从命令文本确认脚本绝对路径，再读取同目录 `registry.json` 版本并比较脚本哈希；不得依据另一份同名目录的状态判断当前进程。部署后应在实际调用路径用 WorkBuddy 的 MSYS 环境执行两次真实 `sync` 和一次 `sync-if-needed`。
- **修复**：将 57 个受跟踪技能文件完整同步到工作区本地副本，保留其 `.env`，清理 8 个旧 snippet；实际调用路径升级到 1.4.2 后，两次 `sync` 和一次 `sync-if-needed` 均返回 0，9 个目标字节稳定、Schema 为完整 8 模块且无临时残留。用户技能目录与工作区本地副本现均与开发仓库一致。

## 2026/07/12 —— `CST` 被误解为中国标准时间，日期边界偏移 14 小时

- **现象**：计算 2026-07-01 起始时间时使用 `date -d "2026-07-01 00:00:00 CST"`，得到 `1782885600000`，导致 `expectedEndTime BETWEEN` 漏掉 CRM 中日期为 2026-07-01 的安徽雪龙商机；API 返回的正确值是 `1782835200000`。
- **根因**：GNU `date` 的裸 `CST` 表示北美 Central Standard Time（UTC-06），不是中国标准时间（UTC+08），两者相差 14 小时。`1782835200000` 实际表示 `2026-06-30 16:00Z = 2026-07-01 00:00 Asia/Shanghai`，不是 UTC 午夜。另有 5 处写入解析使用 `time.mktime`，会随宿主机时区漂移。
- **正确做法**：相对时间优先使用 `DYNAMICS`；明确自然日区间执行本地 `cordys.sh crm date-range <开始日> <结束日>`，两端日期按 `Asia/Shanghai`（固定 UTC+8）闭区间处理。禁止 `CST`、`TZ=Asia/Shanghai date` 等依赖环境 tzdata 的 shell 算法；Unix 毫秒戳本身没有时区。
- **修复**：新增 `scripts/sop/time_boundary.py` 和 `crm date-ms/date-range`（纯本地、无需凭证），统一替换 `create_entity`、`transform_lead`、跟进记录/计划、更新内联逻辑和查重展示中的本地时区转换；显式非法日期不再回退当前时间或原字符串写入。修正 CLI/表单/流程文档及错误示例，版本升级到 1.4.3；新增时区独立回归测试，全套 `117 passed, 29 subtests`。真实 CRM 只读验证：正确区间命中安徽雪龙 `total=1`（`expectedEndTime=1782835200000`），旧 CST 区间 `total=0`。

## 2026/07/12 —— 查询输出管道掩盖失败，MSYS/Windows 编码与临时路径导致反复重试

- **现象**：团队月度复盘查询先把 `opportunity.stage` 写成 `SELECT_MULTIPLE`，CLI 已拒绝，但命令追加 `2>&1 | head -c 5000` 后平台显示 exit 0；修正字段类型后又把 CLI 输出送入裸 `python -c`，先后出现 `UnicodeDecodeError`、Windows Python 找不到 Git Bash `/tmp` 文件，以及 `2>/dev/null` 后只剩空输出 + exit 1。随后模型绕过 CLI 直连 CRM，并把鉴权值写进命令 trace。
- **根因**：`stage` 的真实字段类型是 `SELECT`，`IN/NOT_IN` 的 value 为数组不会把字段变成 `SELECT_MULTIPLE`；Shell 管道最终状态取末端 `head`，会掩盖上游非零；`2>&1` 污染纯 JSON，`2>/dev/null` 隐藏唯一诊断；Git Bash 与原生 Windows Python 对 `/tmp` 和默认编码的解释不同。Shell 查询 helper 还把完整 JSON 放进 Windows argv，大 payload 会触发 `Argument list too long`；`curl -s` 会隐藏网络错误。
- **正确做法**：管道只用于把 UTF-8 请求 JSON 送入 `-`/`@-`，禁止处理 CLI 输出、合并/丢弃 stderr 或用临时文件二次解析。数量读 `pageSize:1` 的 `data.total`；开放管道用 `aggregate opportunity amount sum` + `stage NOT_IN [SUCCESS,FAIL]`（`type:SELECT`）一次取 `count/value`；排名用 `aggregate --by`，阶段分布用 `dist`。禁止读取 `.env` 或在 Python/curl 参数中放鉴权值；本次已经进入 trace 的 CRM 凭据必须轮换。
- **修复**：新增 `scripts/sop/payload_io.py`，Shell 查询 payload 统一经 UTF-8 stdin 进入原生 Python，兼容 BOM 和大 JSON；Shell 强制 Python UTF-8，Python 备用 CLI 的 `-`/`@-` 真正读取 stdin，curl 使用 `-sS` 保留网络错误，失败路径清理临时 payload；schema 错误明确解释 SELECT/SELECT_MULTIPLE。同步更新 SKILL、query-engine、cli-spec、cli-reference、sales-manager、funnel-engine 和 opportunity 表单说明，并新增 transport 回归测试。凭据轮换属于外部管理动作，代码无法代替。

## 2026/07/13 —— “本月回款”误按 createTime 统计录入时间，金额从 2.4 万错成 9.305 万

- **现象**：销售三部本月回款执行 `crm stat contract/payment-record`，时间条件使用 `createTime + DYNAMICS MONTH`，得到 `amount=93050`、`averageAmount=23262.5`（4 笔）；同部门改用实际回款日期 `recordEndTime + MONTH` 后，真实结果为 `amount=24000`、`averageAmount=24000`（1 笔）。
- **根因**：`contract/payment-record` 同时存在 `createTime` 与 `recordEndTime`，两者技术类型都合法，原 query contract 只校验字段/type/operator，无法识别业务口径。模型又把其他模块常用的 `createTime` 机械套给回款：前者表示记录录入 CRM 的时间，后者才是资金实际回款日期，因此后端正常返回 `code=100200` 但业务数字错误。
- **正确做法**：默认“回款、本月回款、回款总额、回款排名、回款趋势”统一使用 `recordEndTime`；只有用户明确说“本月录入的回款记录”时，才允许 `crm page contract/payment-record` 用 `createTime` 查明细。部门条件保持不变，金额字段使用 `recordAmount` 或服务端 `/statistic`。
- **修复**：`query_contract.py` 新增带 query mode 的回款统计语义门禁；Shell/Python `crm stat`、`aggregate` 和 `dist` 在联网前拒绝 `contract/payment-record` 的 `createTime/updateTime` 时间条件，并直接提示改用 `recordEndTime`。同步更新 payment-record 表单、query-engine、cli-spec、funnel-engine、sales-manager 与 SKILL；新增离线正反例测试，并以真实只读统计验证两种时间字段的差异。

## 2026/07/14 —— 查重接口失败被当成空列表，可能错误报告“未查到相关记录”

- **现象**：`check_duplicate.py` 调用任一 `/global/search/{module}` 遇到网络错误、无法解析的 HTTP 错误响应或异常业务响应时，会继续聚合其他分类；如果其余分类也为空，最终可能返回 `hasMatches:false`，把查重失败误报为“未查到相关记录”。
- **根因**：底层 `api()` 用空字典表示请求失败，`search()` 又用 `r.get("data", {}).get("list", [])` 把失败和合法空列表归并成同一种状态，聚合层无法区分“没查到”和“没查成”。
- **正确做法**：已发起的每个分类搜索都必须得到 `code=100200` 且 `data.list` 为数组；任一搜索失败应让整个查重返回 `error`，不得生成 `hasMatches:false`，创建流程必须停止并稍后重试查重。
- **修复**：`scripts/sop/check_duplicate.py` 记录失败的分类并在聚合判断前失败关闭；`sop/duplicate-check.md` 补充错误处理规范；新增网络失败离线回归测试。已同步用户技能目录和 WorkBuddy 实际运行副本，并重新打包 `cordys-crm.zip` 与版本化产物。

## 2026/07/14 —— `check` 裸关键词解析失败但进程退出 0，平台误显示“运行成功”

- **现象**：模型执行 `cordys_ext.sh check "赛摩智能"`，Python 返回 `{"error":"params JSON 解析失败"}`，但 Shell 进程仍退出 0，平台显示“运行成功”；模型随后读取脚本并用 JSON 重试，导致一次查重变成多步试错。
- **根因**：运行时主路由只写 `cordys_ext.sh check`，精确 JSON 模板离执行决策较远；`check_duplicate.py` 只接受 JSON；`cmd_check` 又无条件打印返回字符串，没有检查 `error` 并传播非零退出码。
- **正确做法**：AI 首次直接执行 `cordys_ext.sh check '{"客户名":"<名称>"}'`，仅手机号使用 `'{"手机":"<手机号>"}'`；CLI 可兼容单个裸公司名或手机号作为人工调用兜底。返回体含 `error` 或不是合法 JSON 时，命令必须退出 1，不能以进程启动成功冒充查重成功。
- **修复**：在 `SKILL.md`、`core/intent-engine.md`、`core/cli-spec.md`、角色与查重 SOP 的路由位置加入完整 JSON 示例和“首次不得试错”约束；`check_duplicate.py` 新增标准 JSON/裸关键词归一化；`cordys_ext.sh cmd_check` 校验返回 JSON 并对 `error` 返回非零；新增解析与 Shell 退出码离线测试。已同步两套运行副本并重新打包。

## 2026/07/15 —— 联系人姓名搜索误走全局端点，成功返回空列表

- **现象**：`crm search contact '{"keyword":"李娜",...}'` 请求 `/global/search/contact` 返回 `code=100200` 但 `total=0`；同一实例直接请求 `/account/contact/page`，携带 `viewId=SELF` 和相同姓名关键词，返回 1 条精确匹配记录。
- **根因**：联系人业务列表实际挂在 `/account/contact/page`，`/global/search/contact` 对姓名关键词不可靠（按手机号仍可命中）。CLI 之前把 `contact` 与普通模块一样映射到全局搜索，并把默认范围设为 `ALL`；运行时文档进一步错误声称联系人不支持全局 `keyword`、必须先拿客户 ID。
- **正确做法**：联系人姓名/手机号查询使用 `crm search contact` 或 `crm page contact`，由 CLI 映射到 `/account/contact/page`，默认 `viewId=SELF`；已知客户 ID、需要列出该客户联系人时才使用 `crm contact account <客户ID>`。
- **修复**：修正 `cordys.sh`、备用 `cordys.py`、分页器的联系人路径和默认范围；同步更新 `cli-spec.md`、`write-engine.md`、`SKILL.md`、销售角色、API 参考和联系人路由说明，并补充离线路由回归测试。需同步部署副本并重新打包。

## 2026/07/15 —— 联系人 update 别名未映射，首次读回失败且成功状态可能被清理覆盖

- **现象**：`crm update contact '{"id":"...",...}'` 先请求不存在的 `/contact/get/{id}`，报“GET 未取到现有记录”；改用 `crm update account/contact` 后接口返回 `code=100200`，但调用轨迹仍可能把后续临时文件清理异常描述成 exit 1。只读查回确认目标联系人的职务已成功更新。
- **根因**：查询分页已对 `contact` 做 `/account/contact/page` 特殊映射，但 `get/create/update/batch-update/form/view` 仍直接拼接调用方模块名，联系人别名契约不完整。写命令又把 `rm -f` 作为函数最后一条业务可见命令，收尾失败会覆盖已经完成的 API 请求状态。
- **正确做法**：所有联系人读写命令统一允许 `contact` 别名并映射到 `/account/contact/*`；`account/contact` 显式写法继续兼容。API 返回后保存业务状态，临时文件清理必须是非致命收尾，不能诱导模型重放已成功写入。
- **修复**：Shell/Python CLI 新增统一联系人模块映射；Shell 的 add/update/batch-update 使用非致命、原生 Python 兜底的临时文件清理；更新命令帮助、写入规范、CLI 参考和联系人表单说明，并新增离线路由/退出码回归。需同步两套运行副本并重新打包 1.2.2。

## 2026/07/15 —— `crm pageall` 强制 ASCII 转义，中文在原始输出中显示为 `\\uXXXX`

- **现象**：相同联系人查询中，`crm page contact` 的 stdout 直接包含中文“李娜”，而 `crm pageall contact` 的 stdout 显示 `\\u674e\\u5a1c`；将 pageall stdout 作为 JSON 解析后又能精确还原“李娜”。
- **根因**：pageall 的请求使用 UTF-8 编码、响应使用 `utf-8-sig` 解码，数据链路本身正确；但 Shell 内嵌 Python 在最终汇总输出时调用 `json.dumps(..., ensure_ascii=True)`，主动把所有非 ASCII 字符转成 Unicode 转义。WorkBuddy 直接展示原始 stdout 时，看起来像中文乱码。
- **正确做法**：最终 pageall JSON 使用 `ensure_ascii=False`，并保留脚本已有的 `PYTHONUTF8=1`、`PYTHONIOENCODING=utf-8`；消费者仍按标准 JSON 解析，不对 stdout 做 `grep/head/python` 二次管道处理。
- **修复**：本轮只完成只读复现与根因确认，尚未修改运行脚本；待修 `cordys.sh` 的 pageall 最终序列化，并补充“原始 stdout 直接含中文、JSON 可解析”的离线回归后同步部署和重打包。
- **落地（同日）**：`cordys.sh` 的 pageall 最终序列化现已使用 `ensure_ascii=False`；同步两套运行副本并重打 1.2.2 包后，原始 stdout 将直接输出 UTF-8 中文。
## 2026/07/16 —— 旧统计端点口径不全，pageall 全量 JSON 又会压垮模型上下文

- **现象**：`funnel-engine.md` 混用 `stat-home`、`stat`、`aggregate`、`dist` 和各类 statistic 子资源生成漏斗、金额、分布及排名；实务中这些服务端统计结果存在数据不全。改走 `page` 明细后数据更完整，但大量记录若用 `pageall` 一次性输出，完整 JSON 会进入模型上下文，记录越多越容易超出上下文或造成高 token 消耗。
- **根因**：旧统计入口存在服务端预设范围、时间桶或过滤口径，不能保证与实际业务 page 列表一致；原 `pageall` 又会在内存中收集全部页并把整个 `data.list` 写到 stdout，统计计算发生在模型侧，输出体积随记录数线性增长。
- **正确做法**：所有统计统一以各模块 `page` 端点为数据源。纯计数用 `pageSize:1` 读取 `data.total`；金额、分组、排名和分布用本地 `page-summary` 每页 500 条流式消费并只返回合计与 Top N 摘要。仅用户明确要求完整逐条明细时使用 `pageall`；超大明细应流式导出文件，只把路径、行数、校验信息和小样本返回模型。
- **修复**：重写 `core/funnel-engine.md`，废弃其中全部旧统计方法；扩展分页公共库 `scripts/sop/paginate.py` 并新增 `crm page-summary` 命令，校验数字字段、有限维度分组、分页完整性、Top N 和异常数值；同步更新 SKILL、query/cli/output 文档与 CLI help，并完成离线分页聚合测试。已同步两套运行副本并重新打包。

## 2026/07/16 —— 超大完整明细只能经 pageall 进入 stdout，缺少安全文件交付路径

- **现象**：用户明确需要数万条完整明细时，原有唯一全量入口 `crm pageall` 会先在内存收集全部记录，再把完整 `data.list` 写到 stdout；模型上下文、内存和 token 都随记录数线性增长。临时使用 `pageall | python` 或跨 MSYS/Windows 临时文件二次处理又会重现退出码、编码和路径转换问题。
- **根因**：分页公共库只有“收集全部记录”和“本地聚合摘要”两种消费者，没有逐页写入持久交付文件的受控出口；也缺少原子发布、失败清理、文件哈希、CSV 固定列与公式注入防护。
- **正确做法**：大量完整明细使用 `crm page-export`，逐页消费 `page` 并写入同卷 `.part` 文件，确认写入行数等于服务端 `total` 后原子改名；stdout 只返回绝对路径、行数、页数、字节数、SHA-256、查询哈希和最多 5 条有界样本。JSONL 可保留完整记录；CSV 必须显式选择字段，并对公式前缀转义。导出目录由 `CORDYS_EXPORT_DIR` 或默认 `~/CordysCRM-exports` 控制，文件名不得携带路径且拒绝覆盖。
- **修复**：扩展 `scripts/sop/paginate.py` 的流式导出器，新增 `crm page-export` 路由和 help；失败/中断清理 `.part`，最终文件尽力设置为仅当前用户可读写；更新 funnel/query/cli/output/SKILL 文档并新增 JSONL、CSV、安全文件名、哈希、公式注入和不完整分页离线测试。已同步两套运行副本并重新打包。

## 2026/07/16 —— pageall/page-export 增加无效分支，且本地路径不等于用户可用交付物

- **现象**：引入 `page-summary` 后，运行时仍需在 `page`、`page-summary`、`pageall`、`page-export` 四种命令之间选择；实际交互中 `pageall` 会扩大上下文，`page-export` 返回的是 WorkBuddy 运行机器本地路径，用户未必能访问，二者都没有稳定的产品场景。
- **根因**：把底层“能够全量拉取/写文件”误当成了面向用户的必要能力，没有以最终输出目标收敛命令面。完整全量倾倒既不利于上下文控制，也缺少平台文件上传/下载链路；本地文件路径会形成假交付。
- **正确做法**：查询只保留二选一：看记录、搜索、最近 N 条、分页查看或只问数量使用 `page`；对命中范围内全部记录做总和、平均、分组、分布、排名、漏斗或跨期比较使用 `page-summary`。用户要求大量完整明细时只分页展示并建议增加筛选条件，不生成本地路径，不把全量 JSON 送入上下文。
- **修复**：删除 Shell CLI 的 `pageall`、`page-export` 函数、help 和路由；从分页公共库删除全量收集器与文件导出器；同步清理 SKILL、funnel/query/cli/output、API 和表单文档及相关测试。已同步两套运行副本并重新打包。
## 2026/07/16 —— 模块视图并非统一 ALL/SELF；/view/list 只返回实例自定义视图，follow 别名路径错误

- **现象**：不同表单模块有不同的官方视图（如客户的 `CUSTOMER_COLLABORATION`、商机的 `OPPORTUNITY_SUCCESS`），但 `GET /{module}/view/list` 不返回这些官方项；当前实例仅 `/lead/view/list` 返回一条用户视图 `test`，其他模块为空。旧 `crm view follow/follow-plan` 又分别请求不存在的 `/follow/view/list`、`/follow-plan/view/list`，可能静默返回空或被 raw follow guard 拦截。
- **根因**：Cordys 官方内置视图由前端按模块静态定义，`/view/list` 只下发当前实例、当前用户可见的自定义视图；跟进记录/计划的视图端点还采用嵌套路径 `/follow/record/view/*`、`/follow/plan/view/*`，不能套用普通模块路径。
- **正确做法**：每个模块维护「官方内置视图 + 实例自定义视图」目录。官方项按模块静态维护，自定义项从真实 view 路径同步；用户明确引用自定义视图时才按名称匹配，普通“本月新线索”等仍构造字段条件。视图不能扩大 profile 的 SELF/owner/部门强制范围。
- **修复**：`sync_forms.py` 为八个 forms 生成独立「视图目录」，按模块请求真实 `/view/list`；`cordys.sh`/`cordys.py` 修正 follow/follow-plan view 别名；`query-engine.md`、`cli-spec.md` 增加视图意图判定。自定义视图表只保存 name/id/enable/fixed，不固化 detail 中会过期的动态条件展开值和庞大 optionMap。

## 2026/07/17 —— 可确定的查询值形状错误触发三次失败和多轮源码探查

- **现象**：查询“超过 7 天没跟进的线索”时，模型首次为 `EMPTY` 携带空数组，并为 `DATE_TIME + LT` 传入单元素数字字符串数组；随后依次改成无 `EMPTY.value`、单元素数字字符串数组、单元素整数数组，连续失败 3 次，又执行时间转换、无条件查询和多轮源码搜索，最终才改为整数标量成功。
- **根因**：运行时文档虽已说明 `EMPTY` 不带 value、`LT` 使用整数标量，但契约层对这些语义唯一的外层形状错误只拒绝不修复；旧错误只笼统说明“必须是毫秒时间戳”，没有指出当前值是字符串、单元素数组还是多值数组，模型因而逐层试错并追查实现。
- **正确做法**：不改变业务语义且目标唯一的形状错误由 CLI 在联网前归一化，并明确提示“无需重试”；命令成功时直接消费 stdout。无法唯一修复时，错误只描述当前值形状、目标形状及应调整的层级，不提供可机械套用的固定业务值；模型最多按该诊断修正一次，不得先读脚本、发无条件查询或更换业务字段试探。
- **修复**：`scripts/sop/query_contract.py` 现会删除 `EMPTY/NOT_EMPTY` 的 null、空字符串或空数组占位 value，并把 `DATE_TIME + GT/LT` 的单元素毫秒数组、单元素数字字符串数组或数字字符串归一化为整数标量；多值数组等有歧义输入继续拒绝，并动态报告值形状。同步更新 `SKILL.md`、`core/query-engine.md`、`core/cli-spec.md`，新增契约层与 Shell 首次调用回归；未新增 `crm date-ago`，继续复用现有时间换算能力。

## 2026/07/17 —— “东区公海”被误查为同名东区线索池

- **现象**：用户要求查看“东区公海里最新的 5 个记录”，模型先请求 `/pool/lead/options`，再用同名“东区”池的 id 查询 `crm page pool/lead`，最终把 27,617 条线索池数据描述为“东区线索池（公海）”。正确只读复核显示 `/pool/account/options` 中也有名为“东区”的公海，但对应 `crm page pool/account` 返回“池为空”。
- **根因**：模型先把“公海”当成 lead pool；更关键的是 `core/cli-spec.md §2.5` 的旧示例把“华南公海”“公海有哪些”也统一写成 `/pool/lead/options` 与 `pool/lead`，与模块表中“公海=`pool/account`”冲突。同名“东区”在线索池和公海中同时存在，错误 options 返回成功后进一步掩盖了模块误判。
- **正确做法**：先按用户名词锁定模块：线索池只对应共享线索 `pool/lead`，公海只对应共享客户 `pool/account`；然后只在该模块的 options 内匹配池名。目标模块没有匹配或为空时如实返回，不得跨模块兜底；输出标签必须与实际模块一致，禁止“线索池（公海）”。
- **修复**：重写 `core/cli-spec.md §2.5` 的池查询矩阵和命名示例；在 Agent、SKILL、query/intent/write/output 引擎与 API 参考中加入同一硬映射；CLI help 同时列出两套模块和 options；新增 `tests/test_pool_routing.py` 防止公海示例再次落到 `pool/lead`。需同步两套运行副本并重新打包。


## 2026/07/17 —— 纯查询绕过 6 小时表单/视图同步检查

- **现象**：用户查询“看下销售三部本周新增线索”时，实际依次执行日期边界、部门展开和 `crm page lead`，但没有执行 `sync-if-needed`。用户技能目录的 `.last_sync` 已过期约 43 小时，查询仍直接使用旧的 forms、field schema 与自定义视图快照。
- **根因**：6 小时仅是 `_auto_sync` 的 TTL，不是后台定时任务；旧运行时规则只在写入前强制同步，`cordys.sh` 的纯查询入口也没有调用同步检查。因此缓存过期不会主动产生动作，除非恰好进入 `cordys_ext.sh` 的写入/form/sync-if-needed 路径。
- **正确做法**：确定查询模块后、读取 forms/视图目录前先执行 `cordys_ext.sh sync-if-needed`；未过期只读取时间戳，过期则全量刷新八模块字段、schema 和实例自定义视图。同步失败应失败关闭，不能继续使用可能属于旧时间或其他 CRM 实例的快照。
- **修复**：更新 `SKILL.md`、`core/query-engine.md`、`core/cli-spec.md`，把查询同步提升为读取 forms 前的强制步骤；`cordys.sh` 的 `page`、`page-summary`、`search`、`view` 与 follow 分页入口在联网前调用 `cordys_ext.sh sync-if-needed` 兜底，失败时停止查询并给出直接诊断方式。需同步两套运行副本并重新打包。

## 2026/07/17 —— 用户原话与自定义视图完全同名，仍被拆成 ALL + 字段条件

- **现象**：查询“看下销售三部本周新增线索”前，`sync-if-needed` 已成功，刷新后的 lead forms 明确包含唯一启用视图“销售三部本周新增线索”（viewId=`416727516951662592`）。模型也口头确认看到了该视图，却仍执行 `viewId:ALL + departmentId + createTime`。
- **根因**：旧视图意图规则只允许用户显式说“视图”、引用引号名称或使用“打开/切换”时匹配自定义视图；普通业务短语即使去掉“看下”后与视图名称完全相同，也被强制转换成字段 conditions。模型不是漏读，而是在遵守一条过度保守的规则。
- **正确做法**：先比较原始业务文本，再去掉“请/帮我/看下/查看/查询/列出”等纯查询外壳；若剩余文本与唯一、已启用的自定义视图名称完全一致，直接使用该 `viewId`。精确命中后不从视图名称重复拆部门、时间条件，只叠加角色硬权限和名称之外的额外筛选。部分重合、同义改写和模糊相似仍走字段条件。
- **修复**：更新 `SKILL.md`、`core/query-engine.md`、`core/cli-spec.md` 的视图优先级和示例；同步修改 `sync_forms.py` 生成文案及八个 forms 当前快照，防止下次 sync 恢复旧规则。需同步两套运行副本并重新打包。

## 2026/07/20 —— 线索公海术语被误路由，池分页丢失 poolId 后仍可能联网

- **现象**：业务上 `pool/lead` 既称“线索池”也称“线索公海”，用户还会说“线索（含公海）”；旧规则却把所有“公海”机械映射到 `pool/account`。同时 `/pool/{lead|account}/page` 的 `poolId` 只停留在文档约束，AI 构造或改写 payload 时容易丢失、放进 conditions、写错大小写或传成数字，CLI 仍可能正式请求错误范围。
- **根因**：池术语只按单个名词硬映射，没有先识别业务对象；共享查询契约又把 `pool/lead` 映射到 lead schema、`pool/account` 映射到 account schema，却没有保留池模块身份做顶层 poolId 入口校验。`search` 与 `page` 的 poolId 语义也未在可执行层区分。
- **正确做法**：先按业务对象消歧：线索池/线索公海/线索（含公海）及线索上下文中的公海=`pool/lead`，客户公海/客户池=`pool/account`，无上下文裸公海默认客户公海。具体池 page/page-summary 必须携带 payload 顶层非空字符串 poolId；跨池 search 不使用 poolId，但必须携带非空 keyword。错误需明确报告当前位置/形状、目标位置/形状、options 命令和正确 page 模板，让 AI 一次修正。
- **修复**：`query_contract.py` 新增池查询联网前契约；Shell 在 sync 前做 pool 轻量预检，完整 normalize 后再次校验；`page-summary` 与备用 Python CLI 共享同一规则，并修正 Python 池 search 端点映射；raw 池 page 改为拒绝，防止绕过。同步更新 Agent、SKILL、query/intent/write/cli/output 文档和 API 参考，并新增缺失、错位、大小写、数字型 poolId 及跨池 search 的离线回归。需同步两套运行副本并重新打包。

## 2026/08/03 —— 跟进更新接口不是 PATCH，缺完整必填字段会失败或清空旧值

- **现象**：用户只修改跟进记录或跟进计划的一个字段时，若把该字段直接 POST 到更新端点，会因缺少必填字段失败；即使后端接受不完整请求，也存在未携带旧字段被覆盖或清空的风险。计划与记录的时间、方式字段名又不相同，容易交叉误用。
- **根因**：`FollowUpRecordUpdateRequest` 强制要求 `id`、`content`、`followMethod`、`owner`、`type`，`FollowUpPlanUpdateRequest` 强制要求 `id`、`content`、`method`、`owner`、`type`；两者都是完整对象更新而非 PATCH。计划详情中的 `converted` 还属于必须保留、但不允许用户直接修改的系统状态。
- **正确做法**：先用 `GET /{module}/follow/{record|plan}/get/{id}` 读取条目详情，向用户展示条目 ID、当前值和目标值并确认，再保留资源归属、负责人、模块字段及计划 `converted`，只覆盖用户明确修改的字段，最后向对应 update 端点提交一次。更新 ID 必须是跟进条目 ID，不是父资源 `sourceId`；异常响应后先回读核验，未确认成功时禁止自动重试。
- **修复**：新增 `follow-update`、`follow-plan-update` 和只读 `crm follow-get` 命令，实现详情合并、字段解析、无变化短路、单次提交及失败回读保护；同步更新 `SKILL.md`、写入/意图/CLI 规范、跟进流程、表单与 API 参考，并新增离线回归测试。需同步两套运行副本并按锁定版本 `1.2.3` 重新打包。

## 2026/08/04 —— 统一跟进端点报 No operation permission，被误判为 API 密钥无跟进权限

- **现象**：`crm add follow/record|follow/plan` 请求 `/follow/{kind}/add`，demo 返回 HTTP 500 / `No operation permission`；线索创建正常，遂误判为 API 密钥未开放全部跟进写权限。
- **根因**：CLI 把跟进当普通一级模块，漏掉真实父模块；文档又把写入父资源字段误写为查询用的 `sourceId`。OpenAPI 中统一页面端点与 `/{lead|account|opportunity}/follow/{kind}/*` 是不同操作，前者失败不能证明后者无权限。
- **正确做法**：查询走 `/{module}/follow/{kind}/page` 并在 body 使用 `sourceId`；写入沿用通用 CRUD，把模块直接写成 `<lead|account|opportunity>/follow/<plan|record>`，JSON 携带 `type` 和对应的 `clueId/customerId/opportunityId`。
- **修复**：仅扩展写入模块白名单并修正查询 URL、运行时文档和离线路由测试；通用 `crm add/update` 逻辑保持不变。未执行真实写入。

## 2026/08/05 —— 报价单不能完全套用普通模块的查询路径与局部更新

- **现象**：报价单只能分页查询，通用 `crm get/search` 会分别请求错误的 `/{module}/{id}` 和 `/global/search/{module}`；新增、修改又被写入模块白名单拒绝。
- **根因**：报价单详情使用专用 `GET /opportunity/quotation/get/{id}`，搜索能力由 `POST /opportunity/quotation/page` 提供；更新请求是完整对象而非 PATCH。
- **正确做法**：报价单列表/搜索走 `/opportunity/quotation/page`，详情走 `/opportunity/quotation/get/{id}`；创建先取表单并提交 `name/opportunityId/untilTime/products/moduleFields/moduleFormConfigDTO`，更新先读详情并额外保留 `id/approvalStatus` 后完整提交。
- **修复**：只为 `opportunity/quotation` 增加查询特例和通用写入白名单，继续复用现有 `form/add/update` 主流程；未开放批量编辑，未执行真实写入。

## 2026/08/05 —— 工商抬头没有自定义视图列表端点

- **现象**：扩展本地表单快照时，请求 `GET /contract/business-title/view/list` 返回 HTTP 200，但响应不是 JSON，导致原子同步整体失败。
- **根因**：`contract/business-title` 支持表单和分页查询，但没有可用的 `/view/list`，不能套用其他业务模块的自定义视图同步路径。
- **正确做法**：工商抬头同步表单、分页样本和内置视图，不请求自定义视图列表；其他模块仍严格同步各自 `/view/list`。
- **修复**：`sync_forms.py` 将工商抬头自定义视图路径显式设为空并跳过抓取，同时保留非 JSON 响应的可诊断错误；`crm view contract/business-title` 本地返回空自定义视图集合，运行时 API/CLI 文档同步注明该例外。需重新同步部署目录并打包。

## 2026/08/05 —— 合并后的新增/修改入口没有完整复用本地表单流程

- **现象**：main 合并来的合同、回款、发票、工商抬头、报价单和订单 CRUD 虽已进入通用写入白名单，但写入口仍可在未刷新本地快照时执行；部分角色配方继续依赖实时 `crm form`。备用 Python CLI 的 update 又把调用方局部对象直接 POST 到全量覆盖端点，存在清空旧字段的风险。
- **根因**：新增模块只扩展了端点路由，没有同时接入现有 Skill 的 `sync-if-needed → 本地 forms → 父记录定位/冲突检查 → 字段校验 → 确认 → 通用 create/update` 契约；Shell 与备用 Python 的写入前置和更新实现也没有保持同一语义。
- **正确做法**：所有可写模块在 form/create/update/batch-update 前强制检查本地快照；字段、必填项、fieldId 和选项值只读取同步后的本地 forms。更新统一先 GET 当前详情，保全顶层可写字段和全部 moduleFields，再覆盖调用方变更并完整提交；实时 form 仅用于接口诊断和报价单 `moduleFormConfigDTO` 专用补充。
- **修复**：整理 `cordys.sh` 的查询/写入共用快照检查，备用 `cordys.py` 复用 `sync_forms.py` 并补齐读回合并；`sync_forms.py` 为全部可写模块生成创建字段表；同步更新 `write-engine.md`、SKILL 路由、角色配方、CLI/API 参考。仅做离线 mock 回归，不执行真实新增或修改；需同步 WorkBuddy 运行副本并按锁定版本重新打包。

## 2026/08/05 —— WorkBuddy 内置 Bash 缺少 cygpath，原生 Python 找不到同步模块

- **现象**：`cordys_ext.sh sync` 在 WorkBuddy 内置 Bash 中报 `ModuleNotFoundError: No module named 'sync_forms'`；手动导入模块正常。给单次 shell 临时添加系统 Git `usr/bin` 后可以同步，但后续命令因 shell 状态不持久再次失败，`.bashrc` 也不会被加载。
- **根因**：脚本把 Bash 的 `/c/Users/.../scripts/sop` 放入 `CORDYS_TOOLS_DIR`。该路径经环境变量传给 Windows 原生 Python 时不会被 MSYS 自动转换；旧逻辑只有在 `cygpath` 位于当前 `PATH` 时才转换，WorkBuddy 自带 Git runtime 又没有该程序。Git Bash 的 `/tmp` 还是虚拟挂载，不能简单机械改成 `C:/tmp`。
- **正确做法**：CLI 自身必须完成跨运行时路径桥接：在 Git for Windows 中优先用 Bash 内建的 `pwd -W` 取得真实目录，再由已选中的 Python 兼容 `/c/...`、`/cygdrive/c/...`、`/mnt/c/...` 盘符形式。调用方直接运行 CLI，不修改 `PATH`，不依赖 profile，也不外接系统 Git 工具。
- **修复**：`cordys_ext.sh` 与 `cordys.sh` 已移除 `cygpath` 依赖，统一做 Python 原生路径转换；`sync` 在导入前检查 `sync_forms.py` 是否可访问并输出 `TOOLS_DIR/PYTHON` 诊断。同步更新 `SKILL.md`、`core/cli-spec.md`，并以禁用 MSYS 参数转换、路径含空格的 Git Bash 场景回归。需同步两套 WorkBuddy 运行副本并按锁定版本 `1.2.3` 重新打包。

## 2026/08/10 —— 跟进列表已迁移到统一页面端点，旧模块子路径结论过期

- **现象**：前端已使用 `POST /follow/record/page` 和 `POST /follow/plan/page` 查询统一跟进列表，但 Skill 仍强制 `crm follow <kind> <module>` 并请求 `/{module}/follow/{kind}/page`；raw guard 还会拒绝新版全局路径。直接把 URL 去掉模块又会让旧命令中的 `module` 失去范围约束，可能从单一资源查询意外扩大为全量查询。
- **根因**：2026/07/03、07/10 基于当时实例行为沉淀的“列表必须带模块子路径”契约已被新版统一页面控制器取代。新版记录分页请求使用通用分页体，计划分页额外强制 `status`；顶层 `sourceId`、`myPlan` 不属于统一页面请求字段，资源范围应使用 follow 表单中的 `clueId` / `customerId` / `opportunityId` 条件。
- **正确做法**：列表固定请求全局 `/follow/{record|plan}/page`；计划缺省 `status:"ALL"`。按单条资源筛选时，在 `combineSearch.conditions` 中使用对应 DATA_SOURCE 字段、`operator:"IN"` 和 ID 数组；本人范围使用 `viewId:"SELF"`。详情、新增、更新仍按当前结构化命令走 `/{module}/follow/{record|plan}/...`，不要把列表和详情/写入路由混用。
- **修复**：Shell/Python CLI、raw guard、help 与 payload 公共层已切换全局列表路由；新增计划状态校验、旧 `<module> + sourceId` 到明确条件的安全兼容转换，并拦截会被后端静默忽略的顶层资源字段。同步更新 Agent、SKILL、query/CLI/API/跟进流程及表单说明，增加离线路由测试。已在 `https://cordys-demo.fit2cloud.cn` 用 API Key 只读实测：记录/计划均 `code=100200`，客户条件从全局 `656342` 条缩至 `6` 条，线索计划条件精确命中 `1` 条。需同步两套 WorkBuddy 运行副本并按锁定版本 `1.2.3` 重新打包。

## 2026/08/10 —— 查询 conditions 误放 payload 顶层时被静默忽略并返回全量

- **现象**：按合同编码精确查询时把 `conditions` 写在分页 payload 顶层，接口仍返回 `code=100200`，但 `total` 是全库数量、首屏记录与目标编码无关；模型随后错误怀疑 `INPUT + EQUALS` 不受支持。
- **根因**：Cordys 分页端点只读取 `combineSearch.conditions`，不会校验或报错提示顶层 `conditions/searchMode`；公共 payload 归一化又会补一个空 `combineSearch`，旧校验器只检查补出的空条件，导致错误键原样联网。
- **正确做法**：所有结构化条件固定使用 `{"combineSearch":{"searchMode":"AND","conditions":[...]}}`；若返回全库数量，先核对条件位置，不得改猜 operator，也不得把首屏无关记录解释为查无数据。
- **修复**：`query_contract.py` 在联网前拒绝顶层 `conditions/searchMode`，错误信息同时说明错误位置、正确结构和静默扩大范围的风险；同步更新 `core/cli-spec.md`、`references/crm-api.md` 并新增离线回归。需同步两套运行副本并重打锁定版本 `1.2.5` 包。

## 2026/08/10 —— 合同与订单子表 subFields 未落本地，重复字段名失去父级归属

- **现象**：合同/订单详情中的产品子表需要修改「售卖类型」「拆分规则」时，本地 forms 和 `field-schema.json` 只有「订阅/维保/其他」等 `SUB_PRODUCT` 父字段，没有子字段；实时 `optionMap` 又把多张子表的同名字段放在一起，模型只能反复请求表单并猜测 fieldId。一次简单的两字段修改因此演变为多次 form/get/update 调试。
- **根因**：`sync_forms.py` 只遍历 `/module/form` 的顶层 `data.fields`，完全丢弃每个 `SUB_PRODUCT` / `SUB_PRICE` 的 `subFields`。同名子字段属于不同父 fieldId、拥有不同选项 value，扁平化或仅按名称建立索引都会覆盖或串表。
- **正确做法**：本地 schema 必须保留 `父 fieldId → subFields → 子 fieldId → type/options` 的树；先根据记录现有 `moduleFields.fieldId` 确定父表，再只在该父表内解析子字段。更新时保留目标子表完整行数组、行 `id` 和未修改字段，SELECT/RADIO 传所属子字段的选项 value。
- **修复**：`sync_forms.py` 递归归一每个字段作用域，Markdown 自动生成「子表字段参考」，机器 schema 将子字段嵌入所属父字段的 `subFields`；已对真实表单只读同步，合同落地 7 个有字段的子表/140 个子字段，订单落地 6 个子表/137 个子字段，发票订单列表也同步；补充合同与订单同名字段不互相覆盖的离线回归，并更新 Agent、SKILL 与 `write-engine.md`。需同步两套运行副本并重打锁定版本 `1.2.5` 包。

## 2026/08/10 —— 合同/订单 update 必须携带 moduleFormConfigDTO，大 JSON 经 argv 在 Windows 超限

- **现象**：合同或订单子表更新即使已带完整 `moduleFields`，后端仍可能返回 `Contract form configuration cannot be empty`；把详情、表单配置和多行子表拼成完整 JSON 后再通过命令行参数传给 Python，在 Windows 上又可能触发命令行长度上限，导致请求尚未发出就失败。
- **根因**：OpenAPI 中 `ContractUpdateRequest` 与 `OrderUpdateRequest` 都包含 `moduleFormConfigDTO`，其结构为 `ModuleFormConfigDTO.fields + formProp`；正确值不是本地精简 schema，而是当前 `/{module}/module/form` 响应的完整 `data` 对象。旧 Shell 更新链路既没有附加该对象，又通过 argv/环境变量搬运大 JSON，合同和订单子表越完整越容易超限。
- **正确做法**：合同/订单更新先读取当前详情和当前 `/{module}/module/form`，保全现有顶层字段、全部 `moduleFields` 和目标子表完整行数组，再将表单响应 `data` 原样放入 `moduleFormConfigDTO` 后只提交一次。详情、表单、调用方 payload 与最终 body 均以 UTF-8 临时文件或 stdin 传输；大 payload 使用 `printf '%s' '<JSON>' | cordys.sh crm update <contract|order> @-`，不得放入 Python argv。
- **修复**：`cordys.sh` 与备用 `cordys.py` 已为合同、订单自动获取并附加 `moduleFormConfigDTO`，读回合并和大 JSON 改用 UTF-8 文件/stdin；`cordys_ext.sh update` 兼容入口统一委托给该实现，避免绕过保护。同步更新写入/API 文档和离线回归。OpenAPI 与表单仅做只读核验，未执行任何真实合同或订单更新；需同步两套运行副本并重打锁定版本 `1.2.5` 包。

## 2026/08/11 —— create 不支持 @- 且子表模块缺少 moduleFormConfigDTO

- **现象**：通过 `crm create order @-` 并行创建订单时，两条命令都在本地报「add 需要 JSON body」；改成内联 JSON 后，请求虽然到达后端，却返回 `Not Support Key: order.form.config.required`。同一缺陷会影响合同、发票、报价单等带子表的创建，并可能因完整表单配置过大触发 Windows 命令行长度限制。
- **根因**：create 入口只接受以 `{` 开头的 argv 参数，没有读取 `-` / `@-` 的 UTF-8 stdin；写请求也没有像子表 update 那样获取当前 `/{module}/module/form` 并附加 `moduleFormConfigDTO`。若让调用方手工复制完整 form，既容易携带过期配置，又会把约 200 KB 以上 JSON 搬进 argv。
- **正确做法**：根据同步后的本地 `field-schema.json` 是否含 `subFields` / `SUB_*` 识别子表模块。首次且唯一一次写请求前读取当前 form，验证响应 `code=100200` 且 `data` 含 `fields + formProp`，再以 `data` 原样覆盖注入 `moduleFormConfigDTO`；form 获取或校验失败时关闭失败、不得发出写请求。create/update 的大 JSON 统一通过 UTF-8 stdin 或临时文件传输，调用方只提供业务字段和子表行。
- **修复**：Shell 与备用 Python 两套 CLI 的 create 均支持 `-` / `@-`，并以 schema 驱动自动注入子表配置；update 从仅覆盖合同/订单扩展到当前全部四类子表模块（合同、发票、报价单、订单）。公共 `payload_io.py` 增加表单识别、结构校验和 create body 组装，运行时文档同步禁止手工搬 form；新增大 payload、失败关闭、四模块识别及真实 Git Bash mock 回归。仅只读核验 Demo 表单并执行离线 mock，未发起真实业务创建或更新；需同步两套运行副本并重打锁定版本 `1.2.5` 包。

## 2026/08/11 —— 订单创建不能直接套用通用表单：名称由系统生成且存在业务缺省值

- **现象**：同步后的订单表单会列出“订单名”和多个交付字段，通用创建流程因此可能主动拼接 `name`，并要求用户逐项填写交付团队、交付形式、正式 License 申请状态和是否专项交付；这与实际订单业务规则不符，也无法承载后续“一个合同按合同类型拆成多张订单”的编排。
- **根因**：订单仍被路由到 `core/write-engine.md` 的通用五步创建流程，没有独立的合同定位、默认值、逐单确认和 1→N 扩展边界；CLI 只处理传输与表单配置，不会移除订单名或补业务缺省值。
- **正确做法**：订单名完全省略，由系统生成；用户未显式覆盖时，交付团队=线下团队、交付形式=远程交付、正式license申请状态=未申请、是否专项交付=否，并从当前本地 schema 解析字段/选项 ID。拆单矩阵未定义前不得根据合同类型猜测，默认只形成一张草稿；多张订单必须逐单预览、一次确认后顺序提交。
- **修复**：新增 `sop/order-create-flow.md` 作为订单创建唯一业务流程，SKILL、Agent、意图引擎、商务 profile、通用写入及字段文档全部显式路由；`payload_io.py` 在订单首次 POST 前移除 `name`、按 schema 补齐缺失默认项、校验显式覆盖值，失败时关闭写入。新增 SOP 路由和订单 payload 离线回归；未执行真实订单创建。需同步两套运行副本并重打锁定版本 `1.2.5` 包。

## 2026/08/11 —— 纠正：订单 name 实际不能为空，必须携带固定编号占位符

- **现象**：上一条记录错误地把“订单名无需用户填写”解释成请求体省略 `name`；实际创建接口要求 `name` 非空，并要求按 `DQ20260805X004-JumpServer 企业版-${订单编号}` 这类模板传入。
- **根因**：混淆了“无需用户自由填写”和“无需向接口传字段”。订单名称应由 SOP 根据合同编码和产品类型自动组装，而不是由后端从缺失字段开始生成；第三段也不是本地真实订单编号，而是后端识别的固定字面量占位符。
- **正确做法**：订单 payload 顶层必须传 `name`，格式固定为 `<合同编码>-<产品类型中文标签>-${订单编号}`。合同编码取订单表单的“合同编码”字段，产品类型使用中文标签而非产品 ID；`${订单编号}` 必须原样提交。一张订单无法确定唯一命名产品类型时停止补充信息，不猜测拆单规则。Bash stdin 示例中的 JSON 使用单引号，避免 `$` 被 shell 展开。
- **修复**：修正 `sop/order-create-flow.md`、CLI/API 说明和两套 CLI help；`payload_io.py` 在首次 POST 前要求并校验合同编码、产品类型、名称前缀、中文标签段及固定占位符，同时保留四项订单默认值和子表 `moduleFormConfigDTO` 自动注入。新增缺名称、错误前缀/后缀、产品 ID 冒充标签、缺来源字段及 Git Bash mock 回归。旧问题记录保留用于追溯；未执行真实订单创建。

## 2026/08/11 —— 订单创建遗漏合同负责人、收入类型映射和服务子字段

- **现象**：按合同创建后的订单负责人可能变成当前创建人；订单顶层/子表收入类型没有明确继承依据；编辑订单时 `维保`、`专业服务`、`培训服务` 行的“服务”数据源为空，其中测试截图中的培训服务行已出现空服务。
- **根因**：通用 create 预处理无条件剥离 `owner`，与订单“负责人跟合同所有人一致”的业务规则冲突。订单 SOP 又只要求“完整子表行”，没有规定合同到订单的父子表字段映射；合同与订单的父/子 fieldId 不同，部分收入类型 option ID（如“其他”子表）也不同。同步表单把服务 DATA_SOURCE 标为非必填，但实际订单业务要求服务类子表必须选择服务。
- **正确做法**：订单顶层 `owner` 原样传合同详情的 `owner` userId，`ownerName` 只展示。先在合同目标子表内把收入类型 ID 解析为中文标签，再分别映射订单顶层和目标子表字段的选项 ID；一张订单包含多个收入标签时停止，不猜拆单。`维保`、`专业服务`、`培训服务` 每行必须把合同对应行的服务 ID 写入订单目标“服务”子字段；缺服务时创建前补齐。
- **修复**：扩展 `sop/order-create-flow.md` 的合同继承表、确认表、payload 骨架和落库核验；订单 create 改为保留并校验合同 `owner`，要求顶层/子表收入类型一致并归一目标选项 ID，动态识别含“服务”字段的订单子表并在首次 POST 前拒绝空服务。通用模块仍剥离 owner。同步更新写入/API/CLI 说明并新增离线和 Git Bash mock 回归；未执行真实订单创建。

## 2026/08/11 —— 订单创建只传输入字段时公式未在首次 POST 前计算

- **现象**：订单子表创建 payload 只携带服务、价格、数量、年限、折扣、税率等输入型业务字段，创建后虽然能看到系统生成的行 `id` / `price_sub`，但公式字段在首次提交结果中没有计算值；问题不只影响“培训服务”，当前订单的订阅、授权及一体机、维保、专业服务、培训服务、其他六张子表都各有 6 个公式，且订阅、维保、其他还分别依赖不同年限字段。
- **根因**：此前 create 预处理只注入 `moduleFormConfigDTO` 并校验收入类型/服务，没有执行实时表单中的 `FORMULA.formula.ir`；如果简单照搬培训服务的“价格 × 数量”又会漏掉订阅年限、维保年限、订阅/维保年限等原字段。公式字段即使标为必填，也不能证明其引用的原字段非空、为有限数字或能完成除法。
- **正确做法**：调用方继续只提供输入型业务字段；CLI 在首次且唯一一次 POST 前读取当前 `/order/module/form`，动态遍历所有有数据的子表、每一行和全部实时公式，递归计算公式依赖并覆盖调用方旧公式值。每个最终引用的原字段必须存在、非空、为有限数字且可计算，除数不得为 0；公式缺定义、无效 IR、未知运算、循环引用或精度不可保存时关闭失败。最终 POST body 必须已包含全部公式结果；行 `id` / `price_sub` 仍由后端创建后生成。
- **修复**：`payload_io.py` 新增基于实时 form 的 Decimal 公式求值器，支持 `binary` / `field` / `literal`、`+ - * /`、公式依赖、循环检查、实时精度及当前两位截断行为，并对所有活动订单子表逐行校验和写入公式。同步更新订单 SOP、写入/CLI/API/字段说明和 help，新增六子表全公式、实时新增公式、缺年限、缺值、非数字、非有限值及除 0 回归。只读核验 Demo 当前为 6 张子表、36 个公式并完成离线 dry-run（0 次业务写入）；需同步两套运行副本并重打锁定版本 `1.2.5` 包。

## 2026/08/11 —— 订单仅按培训服务最小字段组装，遗漏其他子表业务字段和主表金额公式

- **现象**：根据“培训服务”截图排查后，创建草稿只保留服务、价格、数量、折扣、税率等计算输入，合同原行已有的产品类型、产品SKU、产品版本、描述、购买方式、收入类型、售卖类型、币种、成交指导价和单位等字段没有进入订单；同类风险覆盖订阅、授权及一体机、维保、专业服务和其他子表。子表公式补算后，订单顶层“累计原始订单金额”“有效订单金额”仍可能为空。
- **根因**：把截图中的单个子表误当成字段契约，并把“公式只依赖输入字段”错误扩展成“订单只需提交最小输入字段”；合同与订单子 fieldId 不同，且售卖类型等 SELECT 的 option ID 也可能不同，直接复制或只挑公式源都会丢值。公式执行顺序又只覆盖子表，没有继续解析订单主表 `FORMULA`；有效订单金额引用的调整金额也没有显式输入约束。
- **正确做法**：先同步并读取本地 contract/order forms，遍历订单 form 的全部 `SUB_*` 父字段；按“父表标签 + 子字段标签”映射合同源行每个有值的非公式业务字段，不能只处理培训服务或缩成公式最小集。SELECT/RADIO 固定走“合同 option ID → 中文标签 → 订单 option ID”。先逐行完成所有活动子表公式，再计算全部订单主表公式；当前累计原始订单金额聚合所有子表最终成交价（含税），有效订单金额再减显式调整金额，无调整必须传 `0`。
- **修复**：`payload_io.py` 增加基于当前订单 form 的主表公式求值，支持 `SUM`、子表字段聚合、主表公式依赖、循环/未知函数/缺源字段校验，并覆盖调用方旧值；子表业务校验改为读取 form `rules.required`、一次列出所有缺失字段并归一目标 SELECT/RADIO。订单 SOP、写入/CLI/API/表单说明和 help 已明确全子表完整映射、主表公式及调整金额规则；新增六类子表、完整字段、合同/订单选项 ID 差异、累计/有效金额和失败关闭回归。仅只读核验表单并离线计算，未执行真实订单新增或更新；需同步两套运行副本并重打锁定版本 `1.2.5` 包。

## 2026/08/11 —— 订单 PRICE 引用字段、百分比公式和累计金额存储位置判断错误

- **现象**：订单创建时显式提交产品/服务的 `*_ref_*` 投影字段后，后端仍把这些字段落成空值；税率业务值为 `6` 时，不含税价曾错误算成 `6500 / (1 + 6) = 928.57`；子表公式虽已补算，累计原始订单金额仍没有出现在真实前端 update 请求的 `moduleFields` 中。
- **根因**：把只读引用投影误当成普通可写字段，把 `INPUT_NUMBER.numberFormat=percent` 的展示/存储值直接当作公式操作数，并假设所有主表公式都存放在 `moduleFields`；同时把 `price_sub` 与订单子行 `id` 一并误判为创建后生成字段。真实 update 请求表明：合同与订单子行 `id` 不同，但 `price_sub` 相同；累计原始订单金额字段带 `businessKey=amount`，对应请求顶层 `amount`。
- **正确做法**：用产品/服务 ID 和合同 PRICE 源行的 `price_sub` 建立关联；合同子行 `id` 不复制，`price_sub` 必须继承；`*_ref_*` 只用于创建前必填校验和公式计算，最终 POST 前剥离。百分比业务值保持 `6` 提交，仅在公式求值阶段按 `0.06` 使用。主表公式按当前 form 的 `businessKey` 决定写入位置：`businessKey=amount` 写顶层 `amount`，无 businessKey 的有效订单金额继续写 `moduleFields`。
- **修复**：`payload_io.py` 已接入合同详情读回、PRICE 源行唯一匹配、`price_sub` 继承、引用投影剥离、百分比操作数归一化和按 `businessKey` 写主表公式；Shell/Python CLI 同步读取合同详情。订单 SOP、写入/CLI/API 文档与离线回归已同步更新；验证只组装最终请求体，不执行真实订单 create/update。

## 2026/08/11 —— 组织树与部门展开重复请求同一端点，名称歧义会静默选错

- **现象**：完整组织树使用 `cordys.sh crm org`，按名称展开子部门却使用 `cordys_ext.sh dept-children`；后者再次请求相同的 `GET /department/tree`，并按忽略空格后的名称包含关系取深度优先遇到的第一个节点。当前真实组织树已有 3 组规范化后同名部门，按名称查询可能静默展开错误分支；错误业务响应还可能被解释为空 ID 数组或“部门不存在”。
- **根因**：查询能力被拆在两套 Shell CLI 中，`dept-children` 复制了鉴权、curl 和递归解析代码，没有校验业务 `code`，还把整棵树通过 Windows argv 传给 Python。旧文档建议其权限失败后 fallback 到 `crm org`，但两者使用同一凭证和端点，无法形成独立权限通道。
- **正确做法**：完整树统一使用 `cordys.sh crm org`（或显式 `crm org tree`）；部门及所有子部门 ID 统一使用 `cordys.sh crm org ids [部门名称或ID]`，不传目标时返回全部可见部门。匹配顺序固定为 ID 精确、忽略空格后的名称精确、唯一包含匹配；多个候选必须报错并列出路径与 ID，调用方改用 ID，不得任选第一个。
- **修复**：新增共享 `scripts/sop/org_tree.py`，通过 stdin 校验并解析组织树；Shell 与备用 Python CLI 统一接入 `crm org tree|ids`。`cordys_ext.sh dept-children` 的实现、帮助和分发入口已直接删除，不保留兼容代理；运行时文档和 Agent 全部改用新入口，并新增错误码、空树、名称/ID、重名消歧、Shell/Python 一致性及旧命令移除回归。历史问题条目中的旧命令文本保留用于追溯。

## 2026/08/11 —— update 已落库但 curl 非零触发 Shell 提前退出，模型把空输出误判为可重试失败

- **现象**：执行 `cordys.sh crm update contract` 后合同字段实际已经更新，但命令没有 stdout 且退出码为 1；上层模型因此准备原样重试同一更新，希望获得更具体输出，存在重复写入和副作用风险。
- **根因**：`api_write` 在全局 `set -e` 环境中直接执行 `resp=$(curl ...)`。POST 已到达后端后，只要 curl 因 HTTP 500、超时或传输收尾异常返回非零，Shell 就在赋值语句处提前退出，响应 body 解析、结构化错误输出和上层读回核验全部被跳过。Windows CRLF 下的空响应分隔还可能残留单个 `\r`，被误判成非空 body 后只输出空行。
- **正确做法**：任何写命令的非零退出、超时或空输出都只能判为“状态未知”，绝不能据此自动重发。先解析已收到的业务 body；`code=100200` 即成功。update 没有明确成功 body 时只 GET 一次当前详情，核对调用方明确修改的字段；全部匹配视为成功，不匹配或无法读取则保持 unknown 并交给用户处理。
- **修复**：`scripts/cordys.sh` 显式捕获 curl 状态并规范化 CRLF，始终保留响应解析/结构化输出；`crm update` 固定单次 POST，异常后新增一次只读字段核验，输出 `verifiedAfterTransportError:true` 或 `writeState:unknown,retryAllowed:false`；batch-update 确保失败路径清理临时 payload。同步更新 `SKILL.md`、`core/write-engine.md`、`core/cli-spec.md`，新增 fake curl 离线回归覆盖成功 body + curl 非零、超时已落库、超时未确认和批量清理；未再次执行真实写操作。

## 2026/08/11 —— 成员错误参数被静默忽略后扩大到全公司，扁平部门 ID 又被误作层级

- **现象**：按东区销售一、二、三部查询在职成员时，先后尝试单数 `departmentId` 和顶层 `enable:true`；两者都被 `/user/list` 静默忽略，结果返回含总部、停用账号在内的 148 人。模型一度凭第一条记录误判过滤生效，随后反复重查，并准备把 stdout 保存到临时文件交给 Python 过滤；做“部 → 组”汇总时又根据 `org ids` 的扁平数组顺序猜父子关系。
- **根因**：请求过滤字段与响应展示字段不同：成员范围必须是顶层复数 `departmentIds`，在职请求必须是 conditions 中的 `status=true`，而 `enable` 只存在于响应。`members_query.py` 原先允许未知顶层字段透传；单数范围字段失效后还会触发自动补全全部可见部门。`org ids` 的职责只是范围展开，仅返回 ID，无法承载 parent/path/depth；compact 响应又缺少可与组织树稳定连接的 `departmentId`。
- **正确做法**：范围过滤使用 `crm org ids` 的完整数组；层级分析另用 `crm org outline`，按 `parentId/path/depth` 处理；在职名单固定执行 `crm members '{"departmentIds":[...]}' --active --compact`，用成员 `departmentId` 连接 outline 的 `id`。直接消费 CLI 输出，禁止试探无效字段、临时文件或本地 Python 二次过滤。历史打卡工具若只支持单人姓名，最终名单确定后受控并发，不能串行试探或把失败当 0。
- **修复**：Shell/Python 两套 CLI 新增 `crm org outline` 和 `members --active`；成员 helper 在联网前拒绝单数 `departmentId`、顶层 `enable/status` 及冲突状态条件，`--active` 自动注入正式条件并校验所有响应成员均为 `enable=true`，compact 增加 `departmentId`。同步更新 Agent、SKILL、查询引擎、CLI help/spec，并新增错误参数、范围不放大、状态注入/冲突、后端忽略过滤、层级相对深度和两套 CLI 一致性离线回归；未查询真实成员或打卡数据。

## 2026/08/11 —— `/user/list` 的 departmentIds 只精确匹配，父部门不会自动包含下级组

- **现象**：把东区销售一部、二部、三部三个父部门 ID 直接传给 `crm members --active --compact` 时只返回 5 名直属成员，结果中也缺少多个下级组。模型据此怀疑 compact 截断，随后准备逐个执行 `crm org ids` 展开后重查。
- **根因**：`POST /user/list` 的顶层 `departmentIds` 只对所给部门做精确匹配，不递归组织树；原 CLI 又把“显式传了 departmentIds”当成已经完整展开，直接请求成员端点。父部门下面实际挂在组/团队子节点的成员因此全部被漏掉。
- **正确做法**：成员查询仍只使用 `crm members`。调用方可以传一个或多个父部门 ID；CLI 默认先读取一次 `/department/tree`，分别展开“本部门 + 全部子孙部门”、全局去重，再只请求一次 `/user/list`。只有用户明确只查直属成员时才加 `--exact-departments`。需要父子层级归属时另用 `crm org outline`，不要从展开后的扁平数组猜层级。
- **修复**：`scripts/sop/members_query.py` 新增父部门递归展开、未知/不可见 ID 关闭失败、循环/冲突检测及 `--exact-departments`；Shell/Python CLI、Agent、SKILL、query/CLI/API 文档和离线测试同步更新。未查询真实成员数据；需同步两套运行副本并重打锁定版本 `1.2.5` 包。

## 2026/08/11 —— 多订单由调用方逐条 create 会提前回写并放大部分成功重跑风险

- **现象**：一个合同含多个产品或多个收入类型时，如果模型自行拆成多条 `crm create order`，某张成功后就可能更新合同“是否已拆订单”，后续订单尚未创建却被防重拦截；若中途超时或 HTTP 500，整批重跑还会重复创建已经落库的订单。
- **根因**：原订单入口一次只物化一张 payload，没有统一批次边界，无法在首个写请求前确定全部“产品/服务 + 收入类型”组合，也无法跨多张订单统一分摊合同调整金额、追踪已成功 ID 或把合同回写延迟到批次末尾。
- **正确做法**：一次 `crm create order` 只传合同 ID和可选公共默认字段。CLI 在零写入阶段完成全部分组、字段映射、公式与金额分摊，再按源行首次出现顺序逐张调用 `/order/add`，每张最多一次 POST。任一失败或状态不明立即停止并返回 `createdOrders`、`retryAllowed:false`；全部订单成功后才单次更新合同拆单标记。订单名称继续使用既有模板，不追加收入类型。
- **修复**：`payload_io.py` 新增按具体产品/服务 ID + 收入类型标签的完整计划器；新增 `scripts/sop/order_batch.py` 负责无重试顺序创建、假失败成功码识别、部分成功停止和合同回写读回核验；两套 CLI 默认委托批次入口，SOP/写入/API/字段/角色文档及离线 fake transport 回归同步更新。未执行真实订单创建或合同更新；需同步两套运行副本并重打锁定版本 `1.2.5` 包。

## 2026/08/24 —— PRICE 目录主 ID 被当作产品身份，自动拆单同时出现少拆与多拆

- **现象**：MaxKB、DataEase 等不同产品共用同一 PRICE 目录且收入类型相同时，会先被错误合并，随后因一组对应多个产品类型而在首次 `/order/add` 前失败；反过来，同一业务产品来自不同子表或不同产品/服务选择器时，又会被拆成多张名称和收入类型看似重复的订单。
- **根因**：自动拆单把各子表裸“产品/服务”DATA_SOURCE 值与“其他”子表产品类型值混入同一 `group_key`。前五类 PRICE 字段保存的是价格目录主 ID，不是具体产品 ID；这些不同业务维度不能作为统一产品身份。具体产品已经由每行“产品类型”投影给出，并且也是订单顶层产品和名称的实际依据。
- **正确做法**：分组键统一使用“产品类型 ID + 收入类型中文标签”。PRICE 目录主 ID 与 `price_sub` 只作为源行关联信息保留并写入对应子表，不参与分组；共享目录的不同产品分别创建，同一产品跨子表/选择器合并，同组保留全部源行。
- **修复**：`scripts/sop/payload_io.py` 改用产品类型作为唯一分组身份，批次 `groupKey` 同步改为 `productTypeId + incomeType`，并在 `sourceRows` 保留每行原产品/服务选择器便于核验；新增“同 PRICE 目录不同产品必须分开”和“同产品跨子表必须合并”回归。同步更新 Agent、SKILL、SOP、CLI help、写入/API/字段/角色文档；版本锁更新为 `1.2.7`，需同步两套运行副本并重打同版本包。未执行真实订单创建、更新或删除。

## 2026/08/24 —— 合同枚举字段映射到订单文本字段时误写 option ID

- **现象**：合同“其他”子表拆成订单后，币种和单位显示为 `178368447861900001`、`178368448699300001` 等 ID，而不是 `CNY`、`年`；同字段的其他选项也会出现相同错误。
- **根因**：合同币种/单位是 `SELECT`，订单“其他”中的同名目标却是 `INPUT`。旧桥接函数只在目标也是 `SELECT/RADIO` 时执行标签转换，目标为文本时直接返回源值，导致合同 option ID 原样写入订单。
- **正确做法**：源字段为 `SELECT/RADIO` 时始终先把 option ID 解析成标签；目标为 `SELECT/RADIO` 时再按标签取目标 option ID，目标为 `INPUT/TEXTAREA` 时直接写标签文本，目标为数字、日期、数据源等不兼容类型时在首次 POST 前关闭失败。
- **修复**：扩展 `scripts/sop/payload_io.py` 的枚举桥接规则，新增“其他：币种=CNY、单位=年”的完整拆单 payload 回归及不兼容类型失败关闭回归；同步更新 SKILL、SOP、CLI/API 与订单字段说明。需同步两套运行副本并重打锁定版本 `1.2.7` 包；既有错误订单未自动修改，后续如需更正必须单独确认写操作。
