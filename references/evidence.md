# Evidence ledger: pmx-three-views

Evidence ids point into the private evidence pack used for distillation: `U<n>` = the n-th user turn of the session digest, `S<n>` = the n-th compaction summary, `notes:<file>` = notes written during the work, `holdout:` = later sessions used to test the skill.

## principles

| item | status | evidence |
|---|---|---|
| 先问清要的是「工程视图」还是「参考后重新设计的设定图」。前者是渲染现有模型，一根线都不画；后者要改造型，工作量和交付物完全不同。答错方向，后面全白做。 | observed | 用户在看到成品后专门追问「你是直接用 blender 导出，而不是参考建模自行设计吗」，说明这一步必须先讲清楚 |
| 材质的颜色只取 base tex 直连 Emission（unlit 贴图色），配合 view_transform=Standard。不要用 mmd_tools 原生 shader 加光照：纯环境光会过曝，加方向光会有明暗，而三视图只要固有色。球面贴图和 toon 贴图不要接进来，它们表现的是高光和阴影。 | verified | 原生 shader 加环境光实测过曝；Emission 直连产出的颜色与贴图逐像素对应 |
| 「要不要用 BLENDED」的唯一判据是贴图 alpha 里是否真存在小于 1 的像素，不是 image.depth==32。用 foreach_get 取样后判 buf[3::4].min() < 0.98。误把全 1 的 RGBA 贴图当透明，会让不透明层不写深度、alpha 累积，整个角色变半透明。 | fixed | 某角色 26 个材质贴图全是 RGBA 但 alpha 全为 1，按 depth 判断后整个人透明；改成真 alpha 判定后恢复 |
| mmd_material.alpha <= 0.001 的材质必须直接接 Transparent BSDF，不要经过 MixShader。PMX 里标成全透明的层在几何上经常覆盖整个头部，走 MixShader 在 DITHERED 下仍会抖成黑斑。 | fixed | 某角色 alpha=0 的备用脸层覆盖全头，是满脸黑斑的真正来源 |
| use_backface_culling 必须设为 not mmd_material.is_double_sided。强制双面会让单面层（如裙子内衬）的背面翻到前面，盖住正确表面，症状是裙子变成一整块纯色。 | fixed | 单面材质的绿色内衬翻上来盖住白裙，剔除背面后恢复 |
| 贴图 alpha 只有在材质判定为「真有半透明」时才与 mmd_material.alpha 相乘。RGB 贴图的 TexImage Alpha 输出采样结果是 0 而不是 1，无条件相乘会把整个材质变全透明。 | fixed | 脸上、裙子上出现黑白网点，根因是 RGB 贴图的 alpha 被当成 0 乘进透明度 |
| 每一批渲染都要做校验加自动重试。EEVEE 偶发整张空白：同一角色同一脚本，产出三张完全相同的全透明图，重跑即恢复。判据是 alpha>=128 的像素数小于 5000。 | fixed | 某角色首轮三张图字节数完全相同且全空，单跑一次后正常 |
| 判断「模型坏了」还是「参数没调对」：用 mmd_tools 原生材质加环境光渲一张对照。原生也坏，说明是模型或导入层的问题，不要再调渲染参数。 | fixed | 原生渲染与自建材质出现同样的黑块，据此转向修材质链路而不是猜 UV |
| 中文路径不要走命令行参数。把所有路径写进一个 UTF-8 的 job.json，命令行只传这个 json 的路径，Blender 端读 json。 | fixed | 宿主编码与 Blender 的 argv 解码不一致，中文参数容易损坏 |
| 不要指望自动判断颜色对不对。unlit 渲染下所有表面都是平坦色块，「偏暗」类启发式对深色系角色大面积误报，实测 20/36 张图误报。自动只判空白、缺文件、贴边，颜色必须人工看图。 | observed | 平坦暗块比例对黑衣黑发角色全部误报，无法作为门槛 |
| 先冻结一份「已验收」的基准，再允许任何修改。每次重渲后逐张与基准比：轮廓 IoU 与变化像素占比超阈值就报警。这条能挡住「修好两个、弄坏两个」——实测把某个角色的 alpha 压低后，检测立刻把它标成 REGRESSED，其余角色不受影响。 | verified | 人工模拟一次半透明回归，baseline_guard 只标出被改的那一张 |
| 诊断手段必须做成脚本，不能只写在文档里。同一个隔离实验重复手写三次，第三次一定会漏掉变量（比如把 fac 写死成 1.0）而得出相反结论。material_id_map.py 就是为此存在的：一条命令出 ID 图加对照表。 | fixed | 排查过程中手写过三次隔离脚本，其中一次因为改掉了 alpha 变量而误判成「模型索引错位」 |

## procedure

| item | status | evidence |
|---|---|---|
| 确认交付形态和素材结构 | observed | 用户事后追问是否「自行设计」 |
| 确认 Blender 与 mmd_tools_local 可用 | verified | 带 --factory-startup 时扩展不加载，import_model 直接报 could not be found |
| 先单角色试跑，确认材质链路 | verified | 单角色 25 秒左右，是性价比最高的验证点 |
| 全量渲染，逐角色独立进程 | verified | 12 个角色 5~6 分钟跑完，0 失败 |
| 拼版：每个角色一张 1:1 横排版面，外加总览 | verified | 12/12 sheets ok |
| 自动质检 | verified | 12 角色 36 张图 0 hard-fail |
| 人工看图 | observed | 自动质检放过的两次问题（脸黑、身体透明）都是靠人眼发现的 |
| 冻结基准，之后每次改动都回归对比 | verified | 12 角色 36 视图建基准后自检 36/36 unchanged；破坏一个视图后只标出该视图 |
| 材质异常按固定顺序诊断 | fixed | 隔离脚本里把 MixShader 的 fac 写死成 1.0 会掩盖 alpha 类问题，导致误判成材质索引错位 |

## gotchas

| item | status | evidence |
|---|---|---|
| 脸上或裙子上出现黑白网点 | fixed | 第一轮 12 个角色里两处黑斑 |
| 整个人像半透明，能透过衣服看到腿 | fixed | 某角色 26 个材质全是「RGBA 但 alpha 全 1」，改判据后恢复 |
| 整张脸有一条黑带，换贴图、换纯色都无效 | fixed | 材质 ID 染色图显示问题区域归属该层 |
| 裙子变成一整块纯色，看不到花纹 | fixed | 剔除后白裙、金纹、叶片、薄纱全部恢复 |
| 三张图完全空白，且字节数一模一样 | fixed | 同一角色首轮三张图字节数完全相同 |
| 拼版边缘检测误报，或 PNG 顶部有几个幽灵像素 | fixed | 顶部第 0 行固定 5 个点 |
| 帽子宽的角色横向出画 | fixed | 1.12 余量实测上下各留 5.4% |
| 把道具模型当成了角色本体 | fixed | 多个模型包都有 2~5 个道具 pmx |
| OpenCV 读贴图返回 None | fixed | 贴图修补脚本第一次运行直接 AttributeError |
| 诊断结论自相矛盾：换贴图无效、换纯色也无效，于是误判成材质索引错位 | fixed | 该误判导致隐藏了正确图层、脸偏色发暗，被用户当场指出 |
| 自动质检报一堆「太暗」，但图其实是好的 | observed | 同一批图误报 20/36 |
| 模型怎么调都有一块区域不对 | fixed | 原生渲染出现同样的黑块 |
| 修好两个角色，另外两个又被弄坏 | verified | 把混合模式一刀切改成 BLENDED，修好了黑斑却让另外两个角色整体变半透明 |
| 不知道那块黑斑/纯色是哪个材质画的，逐个隐藏试到崩溃 | verified | 用这个方法在 20 个材质里定位到具体那一层 |
| 换一台机器或进 CI 后，EEVEE 渲染直接失败或输出空图 | observed | 官方渲染文档明确写了这一点；本机有 GPU 所以没触发，Workbench 退化路径已实测 |
| 想用 Khronos PBR Neutral 让颜色更准，结果反而偏色 | verified | 同一模型实测：与 Standard 的像素差均值 9.12，14% 的像素差超过 8 |
