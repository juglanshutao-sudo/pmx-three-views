# 材质与渲染踩坑全记录

按发现顺序记录，每条都真实发生过。细节与判据见 SKILL.md 的 Principles 和 Gotchas。

## 材质与透明度

1. 贴图 alpha 不能无条件相乘：RGB 贴图的 TexImage Alpha 采样为 0，乘进去整材质变全透明。
2. 判 BLENDED 要看 alpha 内容最小值，不是 image.depth。RGBA 但 alpha 全 1 的贴图极常见。
3. alpha<=0.001 的材质直接接 Transparent BSDF，绕过 MixShader。
4. 不能强制双面：use_backface_culling = not is_double_sided。
5. 颜色取 base tex 直连 Emission，view_transform=Standard，无光照。
6. 球面贴图和 toon 贴图不接进 unlit 链路，选 base tex 时要显式排除这两个节点名。

## 渲染

7. EEVEE headless 单帧可行，不需要 GUI；「必须 GUI」只适用于动画序列。
8. EEVEE 偶发整张空白，三张图字节数相同，重跑即恢复，必须校验+重试。
9. 边缘会留 alpha 10~23 的杂散像素，拼版前 alpha<8 清零。
10. 正交取景按 max(高, 宽/宽高比, 深/宽高比)*1.12，不能只按高度。

## 模型与导入

11. 模型导入后朝 -Y：正面 (0,-1,0)、侧面 (1,0,0)、背面 (0,1,0)。
12. 一个包里常有多个 .pmx，道具要排除。
13. 角色名从目录名剥离：去 _by_作者_hash、去【】、去 -模之屋 之类尾巴。
14. 模型自身缺陷用原生材质加环境光渲一张对照，别乱调参数。

## 宿主环境

15. 中文路径写进 job.json，不走命令行参数。
16. cv2 读中文路径要 imdecode(np.fromfile(...))，写要 imencode(...)[1].tofile(...)。
17. 诊断脚本把 MixShader fac 写死成 1.0 会掩盖 alpha 类 bug，导致误判。
18. unlit 渲染做不了自动颜色质检，深色系角色全误报。

## 诊断方法论（成本从低到高）

19. 材质 ID 染色图：每材质唯一纯色，读问题区域像素反查归属。
20. 逐材质隔离：其他接 Transparent，只留一个，且保留真实 alpha。
21. 二分单变量：alpha 强制 1 / 只改混合模式 / 只改剔除。
22. 复制整个模型包改贴图文件再导入，绕开 Blender 图片缓存。

## 时间

- 单角色约 25 秒（DITHERED 为主）；全 BLENDED 会涨到 110 秒，别滥用。
- 12 个角色全量重跑约 5~6 分钟。
- 排查材质问题占了绝大部分时间，渲染本身很快。
