# Cinema 4D MCP：动画与序列渲染使用说明

这个项目连接 MCP 客户端与 Cinema 4D 内的 Python 桥接器。目标版本是 Windows 上的 Cinema 4D 2025.3.2。它不是“所有按钮都已支持”的保证；实际验收范围见 [COMPATIBILITY.md](./COMPATIBILITY.md)。

## 0.4.0 新增内容

- 动画工具接受完整 `path`，可以给数值、开关及向量分量的用户数据控制器打关键帧；旧 `param_id` + `component` 调用仍保留。
- `list_tracks` 返回可直接回传的完整路径；读取、删除关键帧及轨道按同一路径定位，不混淆不同用户数据槽位。
- `set_params` 新增 `{ "link": handle }` 与 `{ "link": null }`，用来设置或清空真实的对象引用参数。所有引用预检通过后才开始写入；仍须检查返回的 `errors`，撤销组不等于所有运行时错误自动回滚。
- `rs_render` 新增明确 `frame`，渲染后恢复时间与活动渲染设置。
- `rs_render_sequence`、`rs_sequence_status`、`rs_sequence_control` 提供有上限的 PNG 主图序列、进度、停止后续帧及同会话续跑。

## 如何向助手提出制作要求

可以直接描述目标，例如：

> 先读取工程状态并保存副本。在指定测试工程中搭建一个两节机械臂，给关节做 0–24 帧旋转动画；检查中间帧，再设置 Redshift 材质、灯光和相机，输出低分辨率 PNG 序列。

助手开始时应调用 `ping` 和 `get_document_state`，确认工程身份。批量场景操作尽量放进指定 `document_name` 的 `batch`。不要用重置整个工程替代局部编辑，不要对用户工程运行测试清理。

### 用户数据动画

1. 用 `add_user_data` 创建参数，或通过 `list_user_data` 读取现有参数。
2. 将返回的 `desc_id` 原样传给 `set_keyframe.path`，同时传对象 `handle`、`frame`、`value`。
3. 不要同时填写 `path` 和旧 `param_id/component`。完整路径包含 SDK 数据类型，不要凭数字猜测。
4. 用 `get_keyframes` 读回，再通过 `sample_transform` 或预览检查实际运动。写入一个控制器值不代表所有表达式和形变都正确。

完整路径接口并不支持所有动画类型。材质节点端口、点级动画、动画层、F-Curve 切线精调、动作重定向仍需单独开发或验证。

### 对象引用

`set_params` 中的一项可以写成：

```json
{
  "path": 12345,
  "value": { "link": { "kind": "object", "path": "/目标对象" } }
}
```

`12345` 只是示意，必须换成从 `describe` 读取的真实引用参数路径。桥接器会核对真实参数类型；普通数值参数不能接收对象引用。通过 `{ "link": null }` 才能明确清空引用，找不到对象不会自动变成空引用。

## PNG 序列

先准备名称唯一的工程和 Redshift RenderData，设置 PNG 格式、合适的分辨率及采样，并明确关闭该设置中的 AOV。输出目录的父目录必须存在，但新任务的输出目录必须不存在。

```json
{
  "document_name": "机械臂",
  "render_data_name": "RS_Sequence",
  "output_directory": "D:\\renders\\arm_take_001",
  "frames": [0, 2, 4, 6, 8, 10, 12],
  "force": true
}
```

将此参数传给 `rs_render_sequence`，保存返回的 `job_id`。随后用 `rs_sequence_status` 查询：

- `running`：逐帧渲染；`current_frame` 为当前帧。
- `cancelling`：已收到停止请求，等待在途帧结束。
- `cancelled`：未完成的后续帧没有继续调度。
- `completed`：所有计划帧均已返回并通过 PNG 结构、CRC、尺寸及文件大小检查。
- `failed`：明确失败，保留已生成文件，不自动重试。
- `uncertain`：连接中断或超时，C4D 可能仍在渲染；不要关闭渲染中的工程或自动重试。

终态还须等待 `settled: true`，表示本进程的收尾写盘已结束。它不代表 `uncertain` 状态下 C4D 已停止。

`rs_sequence_control` 接收 `job_id` 和 `action: "cancel"` 或 `"resume"`。只有正常取消的任务能续跑，续跑前校验已完成文件的 SHA-256。渲染或暂停期间不要修改场景，否则前后帧可能来自不同版本的场景。

### 明确限制

- 每任务 1–300 个不重复帧，非负整数，按帧号升序输出；每 MCP 进程最多保留 20 个任务记录，只同时运行一条序列。
- 本版为 PNG 主图序列，不含 AOV 序列、视频编码、Team Render、跨机器农场、未烘焙模拟或跨进程任务恢复。
- `manifest.json` 和各帧文件会保留在输出目录。控制与续跑必须使用同一个 MCP 服务器进程；重启后不会自动恢复任务。
- 停止只阻止后续帧，不会强行中断 C4D 当前帧。渲染可能占用 C4D 主线程，因此不要同时操作目标工程。
- 不覆盖已有输出。失败帧需要人工检查；不会自动删除可疑文件或不断重试。
- 多个 MCP 客户端/进程之间没有全局队列锁，请勿从多个客户端同时启动序列。
- 不承诺无损模拟缓存恢复、复杂角色变形、透明通道或高位深 EXR 制作质量。

## 测试与安装

```powershell
npm ci
npm run build
npm test
python -m unittest discover -s tests/python
npm run check
npm run install:c4d -- --dry-run
```

普通 `npm test` 和 CI 只运行离线测试，不连接 C4D。审阅安装路径、备份并完全退出 C4D 后，才运行安装器的 `--install`；重新启动 C4D 和 MCP 服务器以加载两侧更新。不要在运行中覆盖插件或热加载模块。

明确允许占用 C4D 后，单工程专项命令为 `npm run test:live:workflow:2025`。它需要桥接器可用、安全门和精确版本符合要求，且只创建一个隔离测试工程；成功或确定失败后清理。如果渲染结果未知则保留现场，不强制关闭。测试跳过不等于通过。

## 后续开发顺序

1. 扩充同一机械场景的控制器和约束验收，再增加更长及更高分辨率序列。
2. 独立补骨骼创建、蒙皮与权重读写、IK/FK、Pose Morph 的专用操作和形变检查。
3. 扩展 UV、动画烘焙、模拟缓存、AOV 序列及可靠的跨进程恢复。

任意 Python 默认关闭；开启它不等于这些功能已经实现、可撤销或被验证。实际时间/求值与渲染处理依据 [Maxon BaseDocument SDK](https://developers.maxon.net/docs/py/2025_3_0/modules/c4d.documents/BaseDocument/index.html) 和 [RenderDocument SDK](https://developers.maxon.net/docs/py/2025_3_0/modules/c4d.documents/index.html)。
