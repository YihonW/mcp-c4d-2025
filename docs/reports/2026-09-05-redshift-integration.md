# Redshift 集成记录：2026-09-05

本记录区分已安装版本、随后完成的源码修复和真实验证。Redshift 生产流程尚未通过完整真实测试，不应宣称全部控制已经可用。

## 已完成

- 11 个 `rs_*` 工具已实现：能力查询、材质创建、PBR 参数/贴图、灯光、摄像机、AOV 查询/增改/删除/清空、渲染设置与正式渲染。工具目录共 76 项；默认关闭的 `exec_python` 不对客户端公开。
- 普通 `npm test` 只执行单元测试；E2E 需要显式启用。严格 Redshift 测试只创建一个随机命名、非活动的临时工程，成功或异常均按唯一名称清理，并核对原工程列表和焦点。
- Redshift 单项测试等待时间为 1920 秒，容纳正式渲染请求的 1800 秒等待；Codex 的 `cinema4d` 配置增加 `tool_timeout_sec = 1860`。超时不能视为渲染取消。
- 安装备份改存于所选 preference 的 `mcp_bridge_backups`，位于 `plugins` 之外。新增测试覆盖完整备份、插件扫描目录无残留和备份 junction 拒绝。
- 依赖仅在现有范围内更新 `fast-uri` 3.1.5 → 3.1.7、`qs` 6.15.3 → 6.16.0。

## 安装与只读运行结果

已审阅 dry-run，确认 C4D 完全退出后安装当时的候选插件：

```text
目标：C:\Users\Yihong\AppData\Roaming\Maxon\Maxon Cinema 4D 2025_789E552B\plugins\cinema4d_mcp_bridge
备份：C:\Users\Yihong\AppData\Roaming\Maxon\Maxon Cinema 4D 2025_789E552B\mcp_bridge_backups\cinema4d_mcp_bridge.backup-2026-09-05T10-23-02.616Z
当时安装源与目标：35/35 个已跟踪文件 SHA-256 相同
```

三个 2026-08-08 旧备份（12-14-56.895Z、12-20-23.163Z、12-56-05.415Z）已完整迁到同一 `mcp_bridge_backups` 目录，各 54 个文件，迁移前后哈希一致。没有删除备份，`plugins` 内旧备份数为 0。

用户手动启动后，`ping`、`get_document_state`、`get_capabilities`、`list_documents` 通过；运行时为 C4D `2025302` / `2025.3.2`、Python `3.11.4`、Windows、bridge `0.4.0`、loopback、token required、`exec_python: false`。当时有一个名为“未标题 1”的活动工程。

通过现有 `batch`（`undo_group: false`）读取 `rs_get_capabilities`：Redshift renderer `1036219`、module、AOV API 可用；资产类型传参错误导致节点查询失败，Area 等灯光常量名称不正确。检查在创建任何工程前停止。本轮没有执行真实场景写入或渲染。

## 只读检查后完成的源码修复

- 资产查询使用 `AssetTypes.NodeTemplate().GetId()`，fake 仓库现在拒绝 declaration 类型参数，能复现真实报错。
- 灯光类型采用安装版 `orslight.h` 中的 `PHYSICAL_AREA`、`PHYSICAL_POINT`、`PHYSICAL_SPOT`、`PHYSICALSUN` 和 `DOME` 符号；Physical、Dome、Sun 分别使用各自参数。Sun 无直接 exposure 参数时明确拒绝。
- Dome 贴图外层 RSFILE 数据类型从对象运行时 description 读取，内层路径使用 STRING；不再使用 BaseContainer/Filename 类型。缺失 description 时在插入对象前报错。
- 新材质的名称通过 SDK 的 `name` 关键字传入，不再把字符串作为 `element`。PBR 更新只取得已有 node material graph，缺失时拒绝，不隐式创建图。
- 图遍历从根节点的子节点开始，兼容 ID 为空的根节点。
- AOV reflection/refraction/normal 对应 SDK 实际的 `REFLECTIONS` / `REFRACTIONS` / `NORMALS` 常量。

首次只读检查结束时，上述源码修复尚未安装；35/35 哈希匹配记录只适用于首次候选安装。修正版的后续安装记录如下，是否成功加载仍需启动后的真实检查。

## 修正版安装：2026-09-05 20:38（北京时间）

- 主目录已整合至提交 `a59a10a`（修复提交 `f8e9ba6`），构建成功。编译后的工具目录为 76 项，默认公开 75 项，其中 11 项为 Redshift 工具。
- 用户保存退出后，再次确认 C4D / Team Render / c4dpy 进程数为 0。审阅 dry-run，并检查源、目标与备份树无 reparse point 后，从主目录安装修正版到上述同一插件目录。
- 旧插件完整备份到 `C:\Users\Yihong\AppData\Roaming\Maxon\Maxon Cinema 4D 2025_789E552B\mcp_bridge_backups\cinema4d_mcp_bridge.backup-2026-09-05T12-38-22.604Z`；备份前后 70 个文件的相对路径与 SHA-256 全部一致。
- 新安装目录与安装源共 62 个文件的相对路径与 SHA-256 全部一致（包括 35 个已跟踪源码文件及本地生成文件）。插件扫描目录内旧备份数仍为 0。
- 本次只安装并核对文件，没有启动 C4D、创建工程或运行真实测试。下一步等待用户手动启动，再验证修正版是否实际加载。

## 离线验证

Node.js `v24.18.0`。以下检查通过，测试未连接 C4D：

| 命令                                                         | 结果                                                 |
| ------------------------------------------------------------ | ---------------------------------------------------- |
| `python -m unittest discover -s tests/python -p 'test_*.py'` | 93 通过，退出码 0                                    |
| `npm test`                                                   | 73 通过，8 个文件，退出码 0                          |
| `npm run check`                                              | TypeScript、lint、格式、Ruff、工具目录一致性通过     |
| `npm run build`                                              | 通过（包含在 tools 文档检查中）                      |
| `npm audit --audit-level=high`                               | 0 vulnerabilities，退出码 0                          |
| 两个 live 标志关闭时运行 `tests/e2e/redshift-2025.test.ts`   | 1 个测试跳过，退出码 0，不连接；这不是 live 通过证据 |

## 下一次真实验证

用户可在离线开发期间正常使用 C4D。原生 Pair 修复 `9dbc0e6` 已于 9 月 6 日 18:14 安装，18:19 的真实测试已通过精确节点 ID 检查，但随后在材质端口查找处失败，详见下文。最新端口查找修复仅在源码中，尚未安装；待用户方便时手动退出，再审阅安装、备份并核验文件。启动后先只读检查，再在用户暂停场景操作的窗口运行一次严格 Redshift 测试；仍只使用一个临时工程并清理，不运行全部历史 E2E。

只有两套严格测试通过、零跳过、输出文件有效且工程列表/焦点恢复后，才能更新 compatibility 中对应的真实验证状态。未来的“全控制”扩展仍需按实际 SDK 能力逐项实现和验证。

## 启动后真实验证：2026-09-05 20:41–20:43（北京时间）

- 已加载版本的源码来自 `a59a10a`，本次未改变配置或安全开关。C4D `2025302` / `2025.3.2`、Windows、Python `3.11.4`、bridge `0.4.0`、loopback、token required、`exec_python: false` 均符合预期。
- `rs_get_capabilities` 只读通过：929 个节点模板、Area/Dome/Sun/Point/Spot 五类灯光、8 个 AOV 别名，以及 renderer/module/material/camera/render 支持均返回可用。这不等同于所有写操作或渲染已经通过。
- 原有工程为活动的“未标题 2”和非活动的 `HX_C04_0905_V8.c4d`。20:41:48 的 foundation 尝试被空白活动工程保护拒绝，退出码 1，未插入工程。没有为绕过保护而修改空白场景或使用 `make_active: true`。
- 明确告知用户后，临时切到已打开的非空 `HX_C04_0905_V8.c4d`。20:42:31 的 `npm run test:live:2025` 通过：1 passed、0 skipped、exit 0，总用时 3.41 秒。创建、变换、读回、撤销、64×64 预览、另存副本和单工程清理均通过。
- 20:42:46 的 `npm run test:live:redshift:2025` 失败：1 failed、0 skipped、exit 1，总用时 3.13 秒。临时工程中对象和材质创建已返回成功，随后 `rs_set_material_pbr` 报 `Standard Material node not found in Redshift graph`。未执行正式渲染，不能宣称 PBR、灯光、摄像机或 Beauty/AOV 流程通过。
- 两次真正插入的测试工程均已清理（串行各一个），两份原工程的名称、路径、顺序保持不变；最后切回“未标题 2”，document state 与开始时一致。没有关闭或保存用户工程。已通知用户可以恢复正常工作，此后只做离线开发。

## 节点 ID 修复与离线复验（安装前记录）

Maxon 官方示例使用 `node.GetValue("net.maxon.node.attribute.assetid")[0]` 取得 ID；SDK 属性是 `(ID, version)`，原实现却对整组值调用 `str()`。将 fake 改为两个 `FakeId` 的 tuple 后，复现了同样的标准材质匹配失败，也暴露了端口路径错误。现在共享 `_node_asset_id` 提取 ID，用于通用节点列表、Redshift 节点匹配和端口定位；缺失值仍按空 ID 处理。未改变已有材质图的重建策略，也未重装或热加载正在运行的插件。

- 材质回归 23 项通过；全部 Python 回归 95 项通过；TypeScript 单元测试 73 项通过，两个 live 标志关闭且测试端口为 65534。
- TypeScript 类型检查、lint、已跟踪文件的格式检查、45 个已跟踪 Python 文件的 Ruff lint/format、构建与工具目录检查通过。
- 主目录 `npm run check` 的全目录格式检查被用户未跟踪目录 `.codex_ref_video1/labels/` 中的 8 个 JSON 文件阻断；全目录 Ruff 另报告该目录中的两个原有 Python 脚本导入排序问题。未格式化或修改这些用户文件；不能把本次完整 `npm run check` 宣称为通过。
- 上述新回归不连接 C4D，不作为最新源码真实兼容性证据。下一次真实测试仍待安装、手动重启和用户暂停编辑的窗口。

## 节点 ID 补丁安装：2026-09-05 20:52（北京时间）

- 安装源为主目录提交 `023406e`。用户确认关闭后，两次检查 C4D / Team Render / c4dpy 进程数均为 0；审阅 dry-run，并确认源、目标与备份树没有 reparse point 后安装。
- 旧插件完整备份到 `C:\Users\Yihong\AppData\Roaming\Maxon\Maxon Cinema 4D 2025_789E552B\mcp_bridge_backups\cinema4d_mcp_bridge.backup-2026-09-05T12-52-23.050Z`，62 个文件的相对路径与 SHA-256 与安装前完全一致。
- 新安装目录与主目录安装源的 70 个文件（含本地生成文件）相对路径与 SHA-256 全部一致，插件扫描目录中旧备份数为 0。
- 本次未启动 C4D、创建工程或运行真实测试。补丁已经落盘，仍需用户手动启动后的加载检查和严格 Redshift 流程验证，不能宣称 PBR 或正式渲染已经通过。

## 原生 Pair 复验与修复：2026-09-05 20:57–21:03（北京时间）

- 启动后只读版本、安全设置与 Redshift 能力检查通过。检查期间工程列表从单个“未标题 1”变为“未标题 2”和 `HX_C04_0905_V8.c4d`，未推定变化原因。按唯一名称向“未标题 1”添加保留标记的请求被拒绝，标记没有创建；20:57:00 的严格测试随后被空白工程保护拒绝，没有插入测试工程。
- 明确告知用户后切到非空工程，20:57:59 再执行一次严格 Redshift 测试：1 failed、0 skipped、exit 1、总用时 3.20 秒。仍在 `rs_set_material_pbr` 报标准材质节点未找到，未进入渲染，测试工程已清理。
- 没有再次盲目重跑整套测试。另作一次只包含创建临时工程、创建诊断材质、读取节点信息、立即关闭的诊断。诊断工程唯一名称为 `e2e_rs_node_diag_1a071a75291`；材质中确有 `standardmaterial@H4UhBxbnDpsqpnJtZdXV0a` 和 `output@VeKy2dNJIBKii87x4T6qjZ` 两个实际节点。
- 运行时节点列表返回的 asset ID 字符串分别为 `(com.redshift3d.redshift4c4d.nodes.core.standardmaterial,)` 与 `(com.redshift3d.redshift4c4d.node.output,)`；根与端口容器为 `(,)`。这说明上一版 `isinstance(value, (tuple, list))` 未覆盖 Maxon 原生容器，仍把 ID/version 整体字符串化。不能把上次普通 tuple 的回归通过视为真实修复通过。
- 当前实现按 SDK 示例直接索引非空属性值的 `[0]`，不再依赖 Python tuple/list 类型判断。测试使用不继承 tuple/list、但支持索引的原生容器替身，字符串形态与实际诊断一致；同时覆盖普通 tuple、空 ID 和 None。
- 修改替身后先复现相同错误，再完成修复：Python 全部 96 项通过，TypeScript 单元测试 73 项通过，类型检查、修改文件 lint/format、构建通过。关闭两个 live 标志且端口设为 65534 时，Redshift E2E 只跳过 1 项、不连接 C4D；这不是 live 通过证据。
- 严格 E2E 增加 PBR 写入前的节点读取和精确 ID 断言。今后该检查失败时会显示实际 ID 列表，避免只留下“节点未找到”的下游错误。
- 本轮实际新建两个临时工程（一次严格测试、一次独立诊断，串行使用），均已关闭；没有批量重试，也没有残留标记。最后恢复“未标题 2”为活动工程，两份原工程的名称、路径、顺序保持不变，并已通知用户可以恢复工作。
- 当时最新修改只在主目录源码中，没有重装或热加载正在运行的插件；后续安装记录如下，真实验证仍待完成。

## 原生 Pair 补丁安装：2026-09-06 18:14（北京时间）

- 安装源为主目录提交 `9dbc0e6`，已跟踪文件无未提交修改；保留全部用户未跟踪素材和 C4D 工程。用户确认关闭后，先后检查 C4D / Team Render / c4dpy 进程数均为 0，审阅 dry-run，并确认源、目标及备份树没有 reparse point 后安装。
- 目标仍为 `C:\Users\Yihong\AppData\Roaming\Maxon\Maxon Cinema 4D 2025_789E552B\plugins\cinema4d_mcp_bridge`；新安装目录与安装源的 70 个文件（含本地生成文件）相对路径及 SHA-256 全部一致。
- 旧插件备份至 `C:\Users\Yihong\AppData\Roaming\Maxon\Maxon Cinema 4D 2025_789E552B\mcp_bridge_backups\cinema4d_mcp_bridge.backup-2026-09-06T10-14-52.659Z`，70 个文件与安装前快照的相对路径和 SHA-256 全部一致。插件扫描目录中的旧备份数为 0，没有删除备份。
- 本轮仅安装和文件核验，没有启动 C4D、修改场景或运行真实测试。需要用户启动并完成工程恢复后，验证实际节点 ID 读取及严格 Redshift 流程；安装成功不等于正式渲染通过。

## 原生 Pair 通过与端口查找失败：2026-09-06 18:19（北京时间）

- 用户手动启动后，只读检查通过：C4D `2025302` / `2025.3.2`、Python `3.11.4`、bridge `0.4.0`、loopback、token required、`exec_python: false`；Redshift 返回 929 个节点模板、五类灯光及 8 个 AOV 别名。
- 开始时只有活动的“未标题 1”，对象和材质均为空。告知用户后，在这个已核实的空白工程中临时添加唯一 Null 标记 `e2e_session_anchor_1a0763a6aa0`，以防 C4D 插入临时工程时自动丢弃空白原工程；未禁用空白工程保护或修改 `make_active: false`。
- 18:19:01 仅运行一次 `npm run test:live:redshift:2025`：1 failed、0 skipped、exit 1，总用时 4.63 秒。测试创建了一个临时工程和 Redshift 材质，读取并精确匹配了 standardmaterial 与 output 两个 asset ID，证实原生 Pair 提取已在真实运行时通过。
- 首次 `rs_set_material_pbr` 随后失败，安装版 `redshift/materials.py:194` 的 `ports.FindChild(maxon.Id(root_id))` 抛出 `TypeError: unable to convert builtins.NativePyData to @net.maxon.datatype.internedid`。错误发生在端口预检、图事务之前，未继续执行 PBR 写入、灯光、摄像机、AOV 或渲染步骤；不能将整个 Redshift 流程标记为通过。
- 测试的 finally 已关闭唯一临时工程；随后按精确 handle 移除原工程中的临时 Null 标记。最终工程列表只有原来的活动“未标题 1”，对象列表为空，读取的 document state 与起点一致。没有保存或关闭用户工程；添加/移除标记可能留下撤销历史，不宣称撤销栈或 dirty 标志完全还原。已通知用户可以继续工作，此后不再操作 C4D。

## 端口查找修复与离线验证：2026-09-06（尚未安装）

- 本机 2025.3.2 的 `GraphNode.FindChild` Python 包装层虽列出 `maxon.Id` 参数类型，实际调用在原生 InternedId 转换处失败。Maxon SDK 专员的纹理端口示例对完整端口 ID 和嵌套的 `path` 均直接传字符串；本次仅将 `_runtime_port` 两处查找参数改为字符串，不改变资产 ID 提取、节点创建或安全开关。
- 收紧端口 fake，不再用 `str()` 自动接受错误参数；修改实现前，24 项材质测试复现同一 TypeError（15 个 error，包含 subTest）。原有回归覆盖输入、输出和嵌套路径，另补入嵌套 colorspace 情况。
- 修复后全部 Python 回归 96 项通过，TypeScript 单元测试 73 项通过；两个 live 标志均关闭，测试端口为 65534，未连接 C4D。这些结果只证明离线回归，不证明端口修复或正式渲染在真实软件中通过。
- TypeScript 类型检查、lint、构建及工具目录一致性检查通过；157 个已跟踪项目文件的格式检查、45 个已跟踪 Python 文件的 Ruff lint/format 和 `git diff --check` 通过。本轮未重跑全目录 `npm run check`，也未修改此前阻断该命令的用户未跟踪素材。
- 未重装、热加载或退出正在运行的 C4D。最新运行版仍是 `9dbc0e6`；新的字符串端口查找补丁等待用户方便时退出后安装与后续真实验证。

## 依据

- 本机 `C:\Program Files\Maxon Cinema 4D 2025\Redshift\res\description\orslight.h`、`drsfile.h`、`drsaov.h`。
- [Maxon 插件结构](https://developers.maxon.net/docs/py/2024_4_0a/misc/pluginstructure.html)：插件目录下 `.pyp` 入口和目录层级。
- [Maxon 2025.3 AssetRepository](https://developers.maxon.net/docs/py/2025_3_0/modules/maxon_generated/frameworks/asset/interface/maxon.AssetRepositoryInterface.html)：资产查询参数。
- [Maxon 2025.3 GraphDescription](https://developers.maxon.net/docs/py/2025_3_0/modules/maxon_generated/frameworks/nodes/interface/maxon.GraphDescription.html)：element 与 name 参数，以及取得缺失 graph 时会创建的语义。
- [Maxon Dome 贴图参数讨论](https://developers.maxon.net/forum/topic/14172/setting-bitmap-in-redshift-dome-light)：RSFILE 复合参数的实际 datatype 和 STRING 子通道。
- [Maxon 节点与贴图路径示例](https://developers.maxon.net/topic/15190/get-value-of-texture-node-filepath-port)：SDK 专员示例中的 `(asset ID, version)` 取值、节点遍历和纹理路径端口。
- [Maxon 2025.3 Pair](https://developers.maxon.net/docs/py/2025_3_0/modules/maxon_generated/datatypes/collection/maxon.Pair.html)：原生容器的继承关系及索引访问。
- [OpenAI MCP 配置](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)：STDIO command/args/env_vars 和 tool timeout。按 OpenAI Docs 核对后保留原启动路径与 token 转发，仅补足渲染等待时间；原配置已备份为 `C:\Users\Yihong\.codex\config.toml.backup-c4d-render-20260905`。
