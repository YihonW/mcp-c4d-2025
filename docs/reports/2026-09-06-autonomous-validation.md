# Redshift 自主维护记录：2026-09-06

用户授权“你自己全权处理吧”后，本轮自行完成保存、正常退出、安装和启动；不强制结束进程、不启用任意 Python 执行、不操作用户素材。最终安装源码 `4a62967` 已通过两套严格真实测试，限定验证范围见下文；不是全部 76 项工具的完成声明。

## 会话保全与安装

- 初始只有活动的“未标题 1”，对象和材质均为空。通过 MCP 另存为 `D:\BaiduSyncdisk\AI\mcp_c4d\备份\自动维护_20260906_1901\未标题1_重启前.c4d`，文件 101973 字节；随后执行运行时枚举确认的“保存”命令 `12098`，窗口标题的未保存星号消失。
- 通过运行时枚举确认的“退出”命令 `12104` 正常退出。确认 C4D / c4dpy / Team Render 进程数为 0 后安装，没有使用强制退出。
- 安装源提交 `7918c58`，包含上一轮 `844f3a0` 的字符串端口查找修复。已审阅 installer dry-run，检查源、安装目录和备份树不存在 reparse point。
- 18:35 安装目标仍为 `C:\Users\Yihong\AppData\Roaming\Maxon\Maxon Cinema 4D 2025_789E552B\plugins\cinema4d_mcp_bridge`。
- 旧版完整备份到 `C:\Users\Yihong\AppData\Roaming\Maxon\Maxon Cinema 4D 2025_789E552B\mcp_bridge_backups\cinema4d_mcp_bridge.backup-2026-09-06T10-35-29.413Z`。备份 70 个文件与安装前快照一致；新安装的 70 个文件与源的相对路径及 SHA-256 全部一致。
- 自行启动原 C4D 2025 可执行文件，保持 loopback、token 认证和 `exec_python` 关闭。以下真实结果须与离线回归分开记录。

## 本次源码修复与离线证据

- VideoPost `SetParameter` 补齐 `DESCFLAGS_SET_0`；RSAOV 的两参数 API 不变。对应 fake 先复现缺参错误，再修复通过。
- 纯 RGB 颜色传入 GraphDescription 前转为 tuple，符合本机 `maxon/frameworks/nodes.py` 的向量转换分支。fake 不再自动容忍 list，先复现再通过。
- AOV 扩展参数改用真实 BaseContainer 迭代 API，不再调用不存在的 `GetCount()`；新增只读 `direct_file_effective_path`，禁止从通用 params 写入或在 fallback 重建时复制该只读值。
- 渲染前按 SDK effective path 检查直接 AOV 的覆盖风险，输出清单也使用该路径；缺失时提前拒绝，不猜测扩展名或回退到原始路径。回归覆盖原始/实际路径不同、实际目标已存在的零渲染保护，以及路径缺失的零渲染保护。
- 严格 E2E 仍只新建一个临时工程：增加纯色后接贴图的材质调用、明确的低采样渲染参数、AOV 独立 PNG/8-bit 设置，以及 Beauty/AOV 的 PNG 签名、IHDR 和 64×64 尺寸检查。
- 离线：100 项 Python、73 项 TypeScript 单元测试通过；类型检查、lint、Ruff、构建和工具目录一致性检查通过。两个 live 开关关闭，测试端口 65534；这些结果不等于真实渲染通过。

## 真实验证

首次启动后，版本、安全设置和 Redshift 能力只读检查通过，并重新打开上述 checkpoint。18:37:11 的严格测试被空白工程保护拒绝，未插入工程；保存过的空工程仍会被 C4D 判作 blank。

随后在已核实为空的 checkpoint 中放置唯一 Null 标记 `e2e_autonomous_anchor_20260906_1837`，未禁用空白工程保护。18:37:28 再执行一次严格 Redshift 测试：1 failed、0 skipped、exit 1，总用时 5.46 秒，实际创建一个临时测试工程。精确节点 ID、端口查找和纯 RGB/标量 PBR 调用通过；贴图 PBR 在颜色空间读回处报 mismatch，未进入灯光或渲染。

测试工程已由 finally 关闭；随后移除临时 Null，核对 checkpoint 对象、材质均为空，正常保存并退出。未留下测试工程或标记。本次尚未通过完整 Redshift gate。

SDK 源码显示 `SetPortValue` 写入 `net.maxon.description.data.base.defaultvalue`，而原事务内校验用的 `GetPortValue` 读取派生属性 `value`。正在修正为核对实际写入属性并增加 expected/actual 类型诊断；当前错误本身未记录两者值，不将“事务内派生值为空”宣称为已观测事实。

### 事务内读回修正版

提交 `310950b` 改为严格核对写入的 defaultvalue 属性，并在 mismatch 中给出预期/实际值及类型。新增模拟派生值尚不可用的回归，静默忽略写入仍拒绝且回滚；材料 25 项、全部 Python 101 项通过。

18:41 再次确认 C4D 完全退出并审阅 dry-run 后安装；备份为 `cinema4d_mcp_bridge.backup-2026-09-06T10-41-01.354Z`，仍在上述 `mcp_bridge_backups` 目录。旧版备份 70 个文件、新版安装与源码 70 个文件均逐项 SHA-256 核验一致。安装后自行启动 C4D，真实结果继续记录如下。

18:42:53 的严格测试实际创建一个临时工程：1 failed、0 skipped、exit 1，总用时 3.64 秒。颜色空间读回已得到 Maxon Data 系对象，但 `read_value != port_value` 触发本机 `maxon/data.py:355` 的 `Data_Compare(self._data, b._data)`，因右边是 Python `str` 报 `_data` 属性不存在。此证据说明必须先做 SDK 原生类型转换，不能直接跨类型比较。测试工程和临时标记 `e2e_autonomous_anchor_20260906_1842` 均已清理，checkpoint 对象、材质为空并正常保存退出；仍未进入渲染。

### 原生值转换与 AOV 完整复制修正版

提交 `9d3b06b` 使用 `MaxonConvert(..., CONVERSIONMODE.TOBUILTIN)` 后严格比较颜色空间读回值。fake 先复现同样的 `_data` 异常；None 仍不能冒充空字符串通过校验。

另核对本机 Redshift 模块自身的 `RendererGetAOVs` / `RendererSetAOVs` 实现：RSAOV 使用 `_SetContainer` / `_GetContainer` 传输，而不是 fake 原先提供的 GetClone/GetDataInstance。本次复制使用供应商相同的完整传输方式，不猜测容器内部结构；原生传输失败明确拒绝，无法建立回滚快照时禁止清空。原始参数的完整枚举仍无已证实 API，返回 `params: {}` 不能解释为没有其他设置。新增 native fake 覆盖格式/位深/额外参数保留、对象独立、完整回滚和传输失败零写入；严格 E2E 增加已有 AOV 更新后的 PNG 输出检查。

全部 Python 105 项、TypeScript 单元测试 73 项通过。18:47 确认 C4D 已退出、审阅 dry-run 后安装；备份 `cinema4d_mcp_bridge.backup-2026-09-06T10-47-01.656Z` 的 70 个文件与旧版快照一致，新安装 70 个文件与源码一致，均逐项 SHA-256 核验。自行启动后继续真实验证，未把离线结果等同于 native AOV 更新成功。

18:48:25 严格测试推进到正式渲染：纯色/贴图 PBR、Area/Dome、摄像机、材质分配、无效贴图拒绝、渲染参数设置及 AOV 创建/更新均返回成功，主图返回非空文件；但 AOV 输出数为 0，故 1 failed、0 skipped、exit 1，总用时 9.69 秒。测试工程清理后另建一个专用诊断工程 `e2e_rs_aov_diag_20260906_1850`，没有并行或批量新建。

同一诊断场景进行 A/B 对比：目标 RenderData 非活动时主图 1046 字节、直接 AOV 缺失；仅将目标 RenderData 设为活动，再渲染另一主图路径，即得到主图 998 字节、depth AOV 354 字节且 expected_missing 为空。这证明该运行时必须让目标 RenderData 处于活动状态才能使用它的 VP/AOV。SDK 返回实际 AOV 路径为 `depth.png.png`，确证不能直接把用户提供的原始 `depth.png` 当落盘路径。

诊断 PNG 保存在 `artifacts/rs_aov_diagnostic_20260906_1850/`，depth PNG 已解码查看。诊断工程和临时标记 `e2e_autonomous_anchor_20260906_1848` 均已清理，checkpoint 对象、材质为空并正常保存退出。接下来修复渲染期间临时激活目标 RenderData、finally 恢复，并要求真实测试核对渲染前后 document state。

### 渲染设置上下文修正版

提交 `4a62967` 从 AOV 有效路径预检开始临时激活目标 RenderData，使用 ExitStack 在所有退出路径恢复原 RenderData，再恢复原活动工程。测试在读取 AOV 和调用 RenderDocument 时均核对目标处于活动状态，覆盖成功、失败码、异常及预检失败后的恢复；render 17 项、全部 Python 106 项通过。严格 E2E 另增加渲染前后 document state 一致性断言，仍以 `make_active: false` 配置目标 RenderData。

18:53 审阅 dry-run、确认 C4D 完全退出后安装；备份 `cinema4d_mcp_bridge.backup-2026-09-06T10-53-40.588Z` 的 70 个文件与旧版快照一致，新安装 70 个文件与源码一致，均通过相对路径和 SHA-256 核验。重新启动后执行最终严格测试。

### 最终通过与清理

- 18:55:09，`npm run test:live:redshift:2025`：1 passed、0 skipped、exit 0，总用时 8.04 秒。覆盖纯色/贴图 PBR、Area/Dome、摄像机位置、材质分配、无效贴图零图修改、低采样 PNG 渲染设置、depth AOV 创建及完整更新、正式 Beauty/AOV 输出。两类输出均核对 PNG 签名、IHDR 和 64×64 尺寸，expected_missing 为空，渲染前后的 document state 完全一致。
- 18:55:34，`npm run test:live:2025`：1 passed、0 skipped、exit 0，总用时 3.93 秒。创建、变换读回、撤销、64×64 预览、保存副本及会话清理通过。
- 两套测试均使用已安装 `4a62967`：C4D `2025302` / `2025.3.2`、Windows、Python `3.11.4`、Node.js `24.18.0`、bridge `0.4.0`、loopback、token 认证开启、任意 Python 执行关闭。Redshift 能力为 renderer `1036219`、929 个节点模板、8 个 AOV 别名。
- 本自主维护轮共实际创建 6 个临时工程：3 个失败的严格 Redshift 工程、1 个 A/B 诊断工程、最终 1 个通过的 Redshift 工程和 1 个通过的 foundation 工程，全部串行且均已关闭；另一次空白保护拒绝没有创建工程。重启时重新打开 checkpoint 不属于测试工程。
- 最终标记 `e2e_autonomous_anchor_20260906_1854` 已移除；只剩活动的 `未标题1_重启前.c4d`，对象和材质列表为空，25 FPS、0–75 帧、当前帧 0、主 take 和原 RenderData 均保持。正常保存 checkpoint 后保持 C4D 打开，已明确通知用户可恢复工作。标记操作的撤销历史不宣称完全还原。
- 严格测试的临时输出由测试自行清理；单独的 A/B 诊断 PNG 保留在上述 artifacts 目录，不是用户生产渲染成品。
- 离线最终计数为 Python 106 项、TypeScript 73 项；依赖审计为 0 vulnerabilities。已跟踪文件的 lint/format、类型检查、构建和工具目录检查通过。未格式化用户未跟踪素材，也未把主目录的完整 `npm run check` 宣称为通过。

## 使用边界

本轮打通的是上述单场景 Redshift 基础生产路径。normal/displacement、其他灯光与 AOV 类型、其他输出格式、AOV 删除/清空、任意节点图等未覆盖选项仍只有离线证据；其他继承工具也不能因本次通过而自动升级为全支持。后续日常请求优先通过现有 MCP 操作指定工程，不自动运行测试或新建测试工程。

## SDK 依据

- 本机 `maxon/frameworks/nodes.py` 的 tuple 向量转换、`c4d/__init__.py` 的 `C4DAtom.SetParameter` 三参数签名和 BaseContainer 迭代接口。
- 本机 `Redshift/res/description/drsaov.h`：独立 FILE_FORMAT、FILE_BIT_DEPTH、只读 FILE_EFFECTIVE_PATH；`vprsrenderer.h`：采样参数。
- [Maxon SDK AOV 示例](https://developers.maxon.net/forum/topic/15352/get-the-names-of-redshift-multi-passes-aov-names-from-the-render-settings/1)：RSAOV 两参数接口及原始/实际路径。
- [Maxon AOV 说明](https://help.maxon.net/r3d/cinema/en-us/Content/html/Intro%2Bto%2BAOVs.html)：直接 AOV 输出格式独立于 C4D Multi-Pass 格式。
