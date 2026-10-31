---
name: pmx-three-views
description: "Render orthographic front / side / back three-views from MMD PMX character models in Blender: one isolated process per character, unlit texture-colour emission materials, exact 1:1 panel scale, transparent PNGs plus a labelled sheet, and a baseline guard that catches the classic fixed-two-broke-two regression. Bundles a batch driver, a sheet compositor, a sanity checker and the baseline differ. Use when asked to 导出或画出角色三视图, to make an orthographic turnaround from .pmx models, when existing renders show black patches on a face, a skirt painted as one flat colour, or a body that looks transparent, or when a fix for one character silently broke another."
---

# 从 PMX 模型导出角色正交三视图（附材质避坑清单）

把一批 PMX 角色模型包渲染成正交三视图（正/侧/背），交付透明底 PNG、每个角色一张带标签的拼版、以及全部角色的总览。产物是「这个模型长什么样」的工程视图：不改造型、不校比例、不补件，模型自身的缺陷也如实呈现。前提是先把材质链路按下面的规则做对，否则会得到黑斑、纯色块或半透明人体。

运行要求：驱动侧 Python 需要 Pillow 与 numpy（拼版、质检、基准比对都用到）；Blender 侧脚本只用 Blender 自带的 numpy，不需要额外安装。Blender 5.x 且配置里已启用 mmd_tools_local。

Evidence tags: VERIFIED = proven by a check or accepted by the user; FIXED = failed first, fix known; OBSERVED = happened, not proven general; INFERRED = plausible, unproven. Details and sources: [references/evidence.md](references/evidence.md).

## When to use

- 用户要「导出/画出角色三视图」「正交转身图」，素材是 MMD 的 .pmx 模型包
- 已有三视图里出现脸上黑斑、裙子一整块纯色、整个人像半透明
- 要把一批角色模型批量出图做建模或绘画参考
- 要判断某个模型是「渲染参数没调对」还是「模型本身坏了」

Not for:

- 要的是「参考模型重新设计的设定图」——本流程零设计成分，改造型属于建模/绘画，是另一件事
- 只有一张平面图、没有 3D 模型：图片转 CAD 或描图属于别的流程
- 要动画序列渲染：EEVEE 动画渲染另有坑，这条流程只覆盖静态单帧

## Inputs

| name | required | example | meaning |
|---|---|---|---|
| `pmx_dir` | yes | models/loli/ | 素材根目录，每个角色一个子目录，子目录里放主 .pmx 和贴图目录（可能有多个 .pmx，道具会被自动排除） |
| `out_dir` | yes | out/three_views/ | 输出根目录，每个角色生成一个同名子目录 |
| `blender_exe` | yes | <blender>/blender.exe | Blender 5.x 可执行文件，且它的配置里装了 mmd_tools_local（operator 前缀 bpy.ops.mmd_tools_local） |
| `character` | no | 七七 | 只跑某一个角色时传角色名，省略则跑全部 |
| `resolution` | no | 1600x2000 | 单张视图分辨率 WxH，透传 run_all.py 的 --res |
| `font_dir` | no | 系统字体目录 | 拼版用的中文字体目录（需要一个常规体和一个粗体）。省略时按 --font 的名字在当前路径找 |
| `baseline_dir` | no | out/three_views_baseline | 已验收版本的基准目录，baseline_guard save 写入、check 读取。只在人眼确认过的那一版上执行 save |

## Principles (non-negotiable)

1. **[OBSERVED]** 先问清要的是「工程视图」还是「参考后重新设计的设定图」。前者是渲染现有模型，一根线都不画；后者要改造型，工作量和交付物完全不同。答错方向，后面全白做。
2. **[VERIFIED]** 材质的颜色只取 base tex 直连 Emission（unlit 贴图色），配合 view_transform=Standard。不要用 mmd_tools 原生 shader 加光照：纯环境光会过曝，加方向光会有明暗，而三视图只要固有色。球面贴图和 toon 贴图不要接进来，它们表现的是高光和阴影。
3. **[FIXED]** 「要不要用 BLENDED」的唯一判据是贴图 alpha 里是否真存在小于 1 的像素，不是 image.depth==32。用 foreach_get 取样后判 buf[3::4].min() < 0.98。误把全 1 的 RGBA 贴图当透明，会让不透明层不写深度、alpha 累积，整个角色变半透明。
4. **[FIXED]** mmd_material.alpha <= 0.001 的材质必须直接接 Transparent BSDF，不要经过 MixShader。PMX 里标成全透明的层在几何上经常覆盖整个头部，走 MixShader 在 DITHERED 下仍会抖成黑斑。
5. **[FIXED]** use_backface_culling 必须设为 not mmd_material.is_double_sided。强制双面会让单面层（如裙子内衬）的背面翻到前面，盖住正确表面，症状是裙子变成一整块纯色。
6. **[FIXED]** 贴图 alpha 只有在材质判定为「真有半透明」时才与 mmd_material.alpha 相乘。RGB 贴图的 TexImage Alpha 输出采样结果是 0 而不是 1，无条件相乘会把整个材质变全透明。
7. **[FIXED]** 每一批渲染都要做校验加自动重试。EEVEE 偶发整张空白：同一角色同一脚本，产出三张完全相同的全透明图，重跑即恢复。判据是 alpha>=128 的像素数小于 5000。
8. **[FIXED]** 判断「模型坏了」还是「参数没调对」：用 mmd_tools 原生材质加环境光渲一张对照。原生也坏，说明是模型或导入层的问题，不要再调渲染参数。
9. **[FIXED]** 中文路径不要走命令行参数。把所有路径写进一个 UTF-8 的 job.json，命令行只传这个 json 的路径，Blender 端读 json。
10. **[OBSERVED]** 不要指望自动判断颜色对不对。unlit 渲染下所有表面都是平坦色块，「偏暗」类启发式对深色系角色大面积误报，实测 20/36 张图误报。自动只判空白、缺文件、贴边，颜色必须人工看图。
11. **[VERIFIED]** 先冻结一份「已验收」的基准，再允许任何修改。每次重渲后逐张与基准比：轮廓 IoU 与变化像素占比超阈值就报警。这条能挡住「修好两个、弄坏两个」——实测把某个角色的 alpha 压低后，检测立刻把它标成 REGRESSED，其余角色不受影响。
12. **[FIXED]** 诊断手段必须做成脚本，不能只写在文档里。同一个隔离实验重复手写三次，第三次一定会漏掉变量（比如把 fac 写死成 1.0）而得出相反结论。material_id_map.py 就是为此存在的：一条命令出 ID 图加对照表。

## How this user wants it delivered

- 中文汇报，先给一句结论，再给可核验的数字（张数、耗时、失败数）
- 不要用「应该好了」这类话；区分为「有产物」「自动检查通过」「人工看过」
- 用户会放大看图并当场指出问题，交付前自己要按同样的标准看一遍

## Procedure

### 1 准备

1. **[OBSERVED] 确认交付形态和素材结构** — 工程视图和设定图是两件事，先讲清楚再动手；顺带确认素材是不是「一个角色一个子目录」
   - check: 能用一句话复述用户要的是「导出模型」还是「设计重画」，且用户认可
   - check: pmx_dir 下每个子目录里都能找到一个主 .pmx
2. **[VERIFIED] 确认 Blender 与 mmd_tools_local 可用** — 扩展装在便携版配置里，换一份 Blender 就找不到 operator
   - `"{blender_exe}" --background --python scripts/render_three_views.py -- <job.json>`
   - check: 不带 --factory-startup 启动，bpy.ops 里能看到 mmd_tools_local
   - check: 日志里出现 [import] meshes=N 而不是 Traceback

### 2 渲染

3. **[VERIFIED] 先单角色试跑，确认材质链路** — 材质规则错一条就会出黑斑/透明，全量跑完再发现问题代价高
   - `python scripts/run_all.py --root {pmx_dir} --out {out_dir} --blender {blender_exe} --only {character}`
   - output: {out_dir}/<角色>/front.png, side.png, back.png
   - output: {out_dir}/<角色>/_render_report.json
   - check: 三张图都非空（不透明像素数远大于 5000）
   - check: 报告里每个材质的 texture_has_alpha / pmx_alpha / transparent 与预期一致
   - check: 放大看脸和裙摆：没有黑斑、没有整块纯色、没有半透明
4. **[VERIFIED] 全量渲染，逐角色独立进程** — 一个坏 PMX 不能毒化整批；顺带拿到每角色的耗时和失败明细
   - `python scripts/run_all.py --root {pmx_dir} --out {out_dir} --blender {blender_exe} --res {resolution}`
   - output: {out_dir}/_render_summary.json
   - check: summary 行是 n/n ok
   - check: 空白图会自动重试一次，重试仍失败的要单独看日志

### 3 排版

5. **[VERIFIED] 拼版：每个角色一张 1:1 横排版面，外加总览** — 三视图必须同比例才有比对价值，所以面板按 1:1 贴、不裁剪
   - `python scripts/assemble_sheets.py --root {out_dir} --font-dir {font_dir}`
   - output: {out_dir}/<角色>/<角色>_三视图.png（5040x2400，300dpi）
   - output: {out_dir}/_总览_全部角色正视图.png
   - output: {out_dir}/_sheet_report.json
   - check: 每个角色都 ok，没有 FAILED
   - check: 面板尺寸必须正好 1600x2000，尺寸不符会直接报错
   - check: 轮廓不许贴边，脚本会断言

### 4 验收

6. **[VERIFIED] 自动质检** — 挡住空白、缺文件、贴边这类机器能判的问题
   - `python scripts/check_views.py --root {out_dir}`
   - output: {out_dir}/_qa_report.json
   - check: hard-fail 为 0/3n
   - check: 平坦暗块占比只作参考，不当作失败判据
7. **[OBSERVED] 人工看图** — 颜色对不对、模型缺陷有没有暴露，只有眼睛能判
   - check: 先看总览：有没有某个角色明显比别人暗、透、缺件
   - check: 再逐个看拼版：正面/侧面/背面三张要一致，不能只有一张对
   - check: 和上一版对比：这次改动有没有把别的角色弄坏
8. **[VERIFIED] 冻结基准，之后每次改动都回归对比** — 用户最容易踩的坑不是单点不会修，而是修一个坏一个；没有基准就无法在交付前发现
   - `python scripts/baseline_guard.py save --root {out_dir} --baseline {baseline_dir}`
   - `python scripts/baseline_guard.py check --root {out_dir} --baseline {baseline_dir} --strict`
   - output: {baseline_dir}/manifest.json
   - output: {out_dir}/_baseline_diff.json
   - check: save 只在人眼确认过的那一版上执行，绝不能在坏图上建基准
   - check: check 的 summary 必须是 n/n unchanged
   - check: 出现 REGRESSED 要回滚而不是继续调参

### 5 排错

9. **[FIXED] 材质异常按固定顺序诊断** — 逐层试错很贵；先把「归属」和「层次」定下来，再动参数，能省掉大半时间
   - `"{blender_exe}" --background --python scripts/material_id_map.py -- {out_dir}/_idmap_job.json`
   - output: {out_dir}/id_map_front.png
   - output: {out_dir}/color_key.json
   - check: 先在 {out_dir}/_idmap_job.json 写明 pmx、out、views，需要看被遮住的层时把材质名填进 hide
   - check: 读问题区域的像素颜色，在 color_key.json 里反查材质名 —— 这一步决定后面查谁
   - check: 再用 --hide 去掉可疑层重渲，看下面露出来的是谁：据此区分「这层本身坏了」和「它盖住了别的东西」
   - check: 最后才二分单变量：alpha 强制 1 / 只改混合模式 / 只改剔除，一次只动一个
   - check: 怀疑贴图时复制整个模型包改文件再导入，绕开 Blender 的图片缓存

## Gotchas

| symptom | cause | fix | status |
|---|---|---|---|
| 三视图整体发灰、颜色发白、对比度低 | 场景默认 view_transform 是 AgX（Blender 4.x 起），它对人眼友好但会压饱和度和高光 | 显式设 scene.view_settings.view_transform='Standard'、look='None'；不设就一定偏色 | FIXED |
| 脸上或裙子上出现黑白网点 | RGB 贴图（无 alpha 通道）的 TexImage Alpha 输出采样为 0，被乘进材质 alpha 后整层近乎全透明，EEVEE 的 DITHERED 把它抖成网点 | 贴图 alpha 只在材质确实有半透明像素时才相乘，其余用 mmd_material.alpha | FIXED |
| 整个人像半透明，能透过衣服看到腿 | 按 image.depth==32 判断要不要 BLENDED，而贴图 alpha 其实全为 1；不透明层在 BLENDED 下不写深度、alpha 累积 | 取样判 buf[3::4].min() < 0.98；只在真有半透明时用 BLENDED | FIXED |
| 整张脸有一条黑带，换贴图、换纯色都无效 | alpha=0 的层（例如备用脸）几何上覆盖整个头部，仍走 MixShader 时被抖出黑斑 | alpha<=0.001 的材质直接接 Transparent BSDF，绕过 MixShader | FIXED |
| 裙子变成一整块纯色，看不到花纹 | 强制双面渲染，单面内衬的背面翻到前面盖住外层 | use_backface_culling = not is_double_sided | FIXED |
| 三张图完全空白，且字节数一模一样 | EEVEE 偶发失败，同一脚本重跑即恢复 | 校验 alpha>=128 像素数，小于 5000 判空并重试一次 | FIXED |
| 拼版边缘检测误报，或 PNG 顶部有几个幽灵像素 | EEVEE 在画面边缘留下 alpha 10~23 的杂散像素 | 拼版前把 alpha<8 清零 | FIXED |
| 帽子宽的角色横向出画 | 只按高度算正交尺寸 | ortho = max(高, 宽/宽高比, 深/宽高比) * 1.12 | FIXED |
| 把道具模型当成了角色本体 | 一个包里常有好几个 .pmx（弓、注射器、哑铃、钻地机、锤子） | 优先取文件名以角色名开头且后缀不超过 4 字的；否则排除道具关键词后取最大的 | FIXED |
| OpenCV 读贴图返回 None | cv2.imread 不支持中文路径 | cv2.imdecode(np.fromfile(path, dtype=np.uint8), ...) 读，cv2.imencode(...)[1].tofile(path) 写 | FIXED |
| 诊断结论自相矛盾：换贴图无效、换纯色也无效，于是误判成材质索引错位 | 隔离测试时把 MixShader 的 fac 写死成 1.0，把 alpha 类 bug 全部掩盖了 | 隔离测试必须保留真实 alpha 链路；一次只动一个变量 | FIXED |
| 自动质检报一堆「太暗」，但图其实是好的 | unlit 渲染所有面都是平坦色块，深色系角色天然命中「平坦暗块」 | 自动只判空白/缺文件/贴边，颜色人工看图 | OBSERVED |
| 模型怎么调都有一块区域不对 | 模型自身的材质/UV 缺陷，不是渲染参数问题 | 用 mmd_tools 原生材质加环境光渲一张对照；原生也坏就停止调参，改用逐角色覆盖表回避并如实告知用户 | FIXED |
| 修好两个角色，另外两个又被弄坏 | 改的是全局渲染参数（材质转换、混合模式、剔除），影响面是所有角色，但只检查了被修的那一个 | 每次改动后跑 baseline_guard 全量对比；只重新渲染受影响角色，其余直接比基准 | VERIFIED |
| 不知道那块黑斑/纯色是哪个材质画的，逐个隐藏试到崩溃 | 没有把材质归属可视化，只能靠猜 | 跑 material_id_map.py，读问题区域像素颜色，查 color_key.json 得到材质名；再 hide 该层看露出什么 | VERIFIED |
| 换一台机器或进 CI 后，EEVEE 渲染直接失败或输出空图 | EEVEE 即使 --background 也需要 GPU 上下文；纯 CPU 环境没有 | 退回 Workbench（light=FLAT / color_type=TEXTURE / view_transform=Standard / film_transparent），或改 Cycles CPU | OBSERVED |
| 想用 Khronos PBR Neutral 让颜色更准，结果反而偏色 | 它会对高光做 rolloff，是给 albedo review 用的压缩曲线，不保证输出等于贴图原值 | 三视图要的是贴图原色，坚持 Standard（唯一做恒等映射的选项） | VERIFIED |
| 更新 skill 后，README / LICENSE / .git 等发布配套文件从目录里消失 | w2s 的 promote 会整体替换输出目录；如果这个目录同时充当 git 仓库，非生成物会被归档进 history 下的历史版本目录 | 发布仓库 clone 到独立目录；或用包装脚本在 promote 前后备份再还原那几个文件 | VERIFIED |

## Verification (done means)

- run_all.py 的 summary 是 n/n ok，且 _render_summary.json 里每项 detail 为 ok
- assemble_sheets.py 输出 n/n sheets，没有 FAILED
- check_views.py 的 hard-fail 为 0/3n
- 参数化版脚本重跑同一角色，与已交付产物对比：尺寸一致、alpha 完全一致、仅 0.002%~0.006% 的边缘像素因 TAA 采样有差异
- 人工看过总览和每张拼版：脸、裙摆、手部没有黑斑/纯色块/半透明

## Limits (do not retry)

- 本流程零设计成分：不改造型、不校比例、不补模型缺的件。用户要「重新设计的三视图」时不能拿它顶替。
- 渲染结果不保证逐字节可复现：EEVEE 的 TAA 采样在不同 GPU 状态下会有微小差异，比对时应当用像素容差而不是字节相等。
- 只覆盖静态单帧。EEVEE 动画序列渲染另有死锁问题，不适用于本流程。
- 依赖 Blender 配置里已装 mmd_tools_local；扩展名或 operator 前缀变了要同步改 render_three_views.py。
- 自动质检判不了颜色，也不能判造型对不对。所有颜色类问题必须人工看图。
- 基准的「正确性」靠人确认：save 只是冻结当前这一版。如果在一版坏图上建基准，之后所有对比都会以坏图为标准。
- EEVEE 的 headless 渲染仍然需要 GPU 上下文。在没有 GPU 的机器（CI、纯 CPU 容器）上会失败。此时退回 Workbench：scene.display.shading.light='FLAT'、color_type='TEXTURE'、view_transform='Standard'、film_transparent=True。实测两个出过问题的角色在 Workbench 下都正常，且完全避开材质转换的坑，代价是不体现球面贴图高光。
- w2s 的 promote 是整体替换目录，不是合并。任何放在输出目录里的非生成物（仓库文件、待办笔记、临时素材）都会在升级时被归档到 history 下的历史版本目录，需要自己还原。

## Bundled scripts

- `scripts/run_all.py` [VERIFIED]: 批量驱动：逐角色独立 Blender 进程、挑主 PMX、跑完校验空白并重试
- `scripts/render_three_views.py` [VERIFIED]: Blender 端 worker：导入 PMX、按四条材质规则重建 unlit 材质、三个正交相机出图。只吃 UTF-8 的 job.json
- `scripts/assemble_sheets.py` [VERIFIED]: 拼版：清理边缘杂散像素、断言轮廓不贴边、每角色一张 5040x2400 版面 + 总览
- `scripts/check_views.py` [VERIFIED]: 自动质检：只判空白/缺文件/贴边，平坦暗块占比仅作参考输出
- `scripts/baseline_guard.py` [VERIFIED]: 基准回归：save 冻结已验收的图集，check 逐张比对轮廓 IoU 与变化像素占比，抓「修一个坏一个」
- `scripts/material_id_map.py` [VERIFIED]: 材质 ID 染色图：每材质唯一纯色 + color_key.json，支持 hide 指定层看下面是谁。定位「这块黑是哪个材质画的」

## References (load when the step needs them)

- [references/material-traps.md](references/material-traps.md): 材质与渲染踩坑全记录（22 条，按发现顺序）
