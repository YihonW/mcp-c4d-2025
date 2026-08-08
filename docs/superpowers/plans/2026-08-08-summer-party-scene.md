# 夏日派对定帧场景还原 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Cinema 4D 2025.3.2 中创建一份独立、可编辑的 Redshift 夏日派对定帧场景，并输出 1280×540 预览图。

**Architecture:** 场景按画框、前景主体、中央舞台、热带背景、灯光摄像机五个根组分层。近景使用三维基础体与挤压文字，中远景使用低复杂度几何和剪影，通过单一锁定摄像机完成构图。

**Tech Stack:** Cinema 4D 2025.3.2、Cinema 4D MCP bridge 0.4.0、Redshift、C4D 原生参数化对象与节点材质。

## Global Constraints

- 只在新建文档 `Summer_Party_Redshift` 中修改场景，不改变当前含 `Male Base` 的未保存文档。
- 渲染器固定为 Redshift，输出分辨率固定为 1280×540，帧率 25 fps，当前帧 0。
- 交付路径固定为 `artifacts/summer_party_scene/summer_party_redshift.c4d` 和 `artifacts/summer_party_scene/summer_party_final.png`。
- 采用 2.5D 定帧还原；镜头不可见的结构和细小装饰不做精细建模。
- 保留 `BOOM` 和 `CFM SUMMER PARTY` 两组主要文字。

---

### Task 1: 安全文档、输出目录与镜头基线

**Files:**

- Create: `artifacts/summer_party_scene/summer_party_redshift.c4d`
- Create: `artifacts/summer_party_scene/summer_party_blockout.png`

**Interfaces:**

- Consumes: 当前 C4D 文档列表与设计说明中的安全约束。
- Produces: 活动文档 `Summer_Party_Redshift`、活动渲染设置 `SummerParty_RS_1280x540`、对象 `CAM_HERO` 和五个根组。

- [ ] **Step 1: 记录并保护当前文档**

  调用 `list_documents` 和 `get_document_state`，确认当前活动文档仍为 `未标题 2`，且场景中存在 `Male Base`；不保存、不关闭、不清空该文档。

- [ ] **Step 2: 创建输出目录和新文档**

  在工作区创建 `artifacts/summer_party_scene`；调用 `new_document(name="Summer_Party_Redshift", make_active=true)`。

- [ ] **Step 3: 创建渲染设置和摄像机**

  创建 `SummerParty_RS_1280x540`，参数为 `renderer="redshift"`、`width=1280`、`height=540`、`fps=25`、`frame_start=0`、`frame_end=0`。创建相机对象 `CAM_HERO`，放置在约 `[0,220,-1500]`，使用 35 mm 左右焦距并设为活动摄像机。

- [ ] **Step 4: 创建场景根组**

  创建空对象 `SET_FRAME`、`FG_HERO_PROPS`、`MID_STAGE`、`BG_TROPICAL`、`LIGHTS_CAM`；将 `CAM_HERO` 归入 `LIGHTS_CAM`。

- [ ] **Step 5: 验证文档隔离和画幅**

  调用 `list_documents`、`get_document_state` 和 `list_entities(kind="object", max_depth=1)`。期望新文档为活动文档、分辨率为 1280×540、五个根组及 `CAM_HERO` 可见，原文档仍在文档列表中。

### Task 2: 画框、地台与天空灰模

**Files:**

- Modify: `artifacts/summer_party_scene/summer_party_redshift.c4d`
- Create: `artifacts/summer_party_scene/summer_party_blockout.png`

**Interfaces:**

- Consumes: `SET_FRAME`、`BG_TROPICAL`、`CAM_HERO`。
- Produces: 可覆盖整个画幅的边框、地台、天空背板和基础空间尺度。

- [ ] **Step 1: 创建舞台围合结构**

  在 `SET_FRAME` 下用圆角立方体建立上横梁、下地台、左右立柱和顶部内框。可见范围控制在 X 约 `[-650,650]`、Y 约 `[-40,540]`、Z 约 `[0,360]`。

- [ ] **Step 2: 创建天空与远景底板**

  在 `BG_TROPICAL` 下创建天空背板、青蓝地面带和两侧建筑块；天空背板位于场景最深处，宽高足以覆盖摄像机画幅。

- [ ] **Step 3: 创建低成本云层**

  用 12–18 个不同尺寸的白色球体组成三组云，分别放在左后、中后、右后，避免遮挡中央舞台区域。

- [ ] **Step 4: 灰模预览验证**

  调用 `preview_render(camera="CAM_HERO", width=1280, height=540, save_path="D:/BaiduSyncdisk/AI/mcp_c4d/artifacts/summer_party_scene/summer_party_blockout.png")`。期望上下边框、两侧立柱完整入镜，地台不超过画面下方约 15%，天空覆盖无空隙。

### Task 3: 中央舞台与热带中远景

**Files:**

- Modify: `artifacts/summer_party_scene/summer_party_redshift.c4d`

**Interfaces:**

- Consumes: 已锁定的相机与灰模空间。
- Produces: `MID_STAGE` 中央 DJ 舞台、`BG_TROPICAL` 棕榈树和两侧建筑剪影。

- [ ] **Step 1: 创建中央 DJ 舞台**

  用立方体搭建底座、台阶和两根音响塔；用圆柱与球体表现喇叭单元。舞台中心保持在 X=0，主体高度约为画面高度的 45%，底部不与前景球体争抢轮廓。

- [ ] **Step 2: 创建中央星形与笑脸标志**

  用星形样条加挤压对象创建舞台中心星标；顶部使用扁球或圆盘、眼睛小球和弧形嘴部构成粉色笑脸标志。

- [ ] **Step 3: 创建棕榈树剪影**

  左右各创建 3–4 棵棕榈树：锥形或圆柱树干，叶片用细长扁平几何围绕树冠放射排列。近侧树更高更宽，远侧树缩小并后移。

- [ ] **Step 4: 创建建筑、遮阳伞与吉他轮廓**

  左侧建立带 `CFM`、`SUMMER`、`PARTY` 三行文字的招牌和集装箱块；右侧建立紫色音响建筑与简化吉他；中后方增加 2–3 把彩色遮阳伞。

- [ ] **Step 5: 层次验证**

  通过 `preview_render` 检查中央舞台位于视觉中心，左右背景重量大致平衡，背景对象不穿过画框或遮挡预留的前景主体区。

### Task 4: 前景标志性道具

**Files:**

- Modify: `artifacts/summer_party_scene/summer_party_redshift.c4d`

**Interfaces:**

- Consumes: `FG_HERO_PROPS` 与当前摄像机构图。
- Produces: 救生圈、碰杯啤酒、沙滩球、音符、笑脸球、`BOOM` 文字和冲浪板。

- [ ] **Step 1: 创建左侧救生圈**

  使用圆环作为主体，叠加四段白色覆盖块和一圈青色绳索近似；整体放在画面左上至左中，保持中心开孔清晰。

- [ ] **Step 2: 创建碰杯啤酒**

  用透明圆柱或锥体表现两个倾斜杯身，内部放置略小的琥珀色液体，杯口堆叠不同尺寸白色球体形成泡沫；杯把使用圆环或扫掠轮廓近似。

- [ ] **Step 3: 创建球体与音乐符号**

  创建三色沙滩球、黄色球、青色笑脸球和粉色笑脸球；音乐符号使用挤压文字 `♪` 与简化音符组合，安排在画面下方中央。

- [ ] **Step 4: 创建 `BOOM` 立体文字**

  创建文字样条 `BOOM`，置于挤压对象下并向右上轻微倾斜；保持文字覆盖右侧中前景，但不遮住中央舞台星标。

- [ ] **Step 5: 创建右下冲浪板**

  使用拉长扁球或胶囊形几何作为冲浪板，增加浅色纵向条纹和棕榈剪影装饰；让其从右下角斜向画面中心延伸。

- [ ] **Step 6: 构图预览验证**

  输出同画幅预览。期望左侧救生圈与啤酒、中央球体与音符、右侧文字与冲浪板形成三个清楚的前景组，轮廓之间保留可读间隙。

### Task 5: Redshift 材质与灯光

**Files:**

- Modify: `artifacts/summer_party_scene/summer_party_redshift.c4d`

**Interfaces:**

- Consumes: 已完成的所有几何对象。
- Produces: 可编辑的 Redshift 节点材质、主光、环境光、轮廓光和霓虹发光效果。

- [ ] **Step 1: 创建糖果色材质组**

  创建青、蓝、紫、粉、黄、绿、白、深蓝八种基础节点材质。使用 Redshift Standard Material，基础粗糙度约 0.25–0.4，非金属，并按对象组统一分配。

- [ ] **Step 2: 创建透明与液体材质**

  为杯体建立高透射玻璃材质，为啤酒建立琥珀色半透明材质；泡沫使用高粗糙度暖白材质。若透明节点连接失败，只回退这两类材质，不改变其他对象。

- [ ] **Step 3: 创建霓虹材质**

  为舞台星标、部分音响细节和主要文字创建粉紫、青蓝、黄色发光材质，控制发光强度以保留字面颜色和边缘。

- [ ] **Step 4: 创建三点式彩色灯光**

  设置暖色大面积主光、青蓝环境补光和粉紫轮廓光；必要时增加一盏顶部柔光照亮啤酒泡沫与球体高光。

- [ ] **Step 5: 材质与灯光验证**

  使用低采样 Redshift 渲染，检查高饱和色块仍有明暗层次，透明杯体可读，泡沫保持白色，霓虹不过曝。

### Task 6: 最终校准、保存与交付验证

**Files:**

- Modify: `artifacts/summer_party_scene/summer_party_redshift.c4d`
- Create: `artifacts/summer_party_scene/summer_party_final.png`

**Interfaces:**

- Consumes: 完整场景、Redshift 渲染设置与参考图。
- Produces: 可重新打开的 C4D 工程和最终 1280×540 PNG。

- [ ] **Step 1: 校准主体位置和颜色**

  对照参考图检查左、中、右三个前景组的面积关系、中央舞台位置、顶部留白和三种主色比例；只调整影响最终镜头的对象。

- [ ] **Step 2: 保存工程**

  调用 `save_document(path="D:/BaiduSyncdisk/AI/mcp_c4d/artifacts/summer_party_scene/summer_party_redshift.c4d", format="c4d")`，随后读取 `get_document_state`，确认活动文档路径指向交付文件。

- [ ] **Step 3: 输出最终 Redshift 图片**

  调用 `render(output_path="D:/BaiduSyncdisk/AI/mcp_c4d/artifacts/summer_party_scene/summer_party_final.png")`。期望输出尺寸为 1280×540，文件非空且渲染无错误。

- [ ] **Step 4: 重新打开验证**

  保持原未保存文档不动，使用 `open_document` 打开已保存工程副本并检查五个根组、活动摄像机、活动 Redshift 渲染设置及主要材质存在。

- [ ] **Step 5: 最终视觉检查**

  查看最终 PNG，确认无主体意外裁切、明显穿插、黑材质、丢失文字或大面积过曝；若发现问题，回到对应对象做最小调整后重新保存和渲染。
