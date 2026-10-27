# PMX Three Views

将 MMD / PMX 角色模型批量渲染为正面、侧面、背面的正交三视图，输出透明 PNG、带标签的同比例拼版和总览图。附带材质排错方法、自动质检和基准回归对比。

An agent skill and Python toolkit for orthographic front / side / back rendering of PMX character models in Blender, with transparent PNGs, labelled sheets and regression checks.

## 内容

- [SKILL.md](SKILL.md)：交给 AI Agent 执行的完整流程、材质规则与避坑清单。
- `scripts/run_all.py`：逐角色启动独立 Blender 进程，检查输出并重试。
- `scripts/render_three_views.py`：Blender 内运行的 PMX 导入与渲染脚本。
- `scripts/assemble_sheets.py`：同比例拼版与总览。
- `scripts/check_views.py`：检查缺图、空白和上下边界；颜色仍需人工判断。
- `scripts/baseline_guard.py`：保存已验收基准，检测后续回归。
- `scripts/material_id_map.py`：材质 ID 染色图与颜色查找表。
- [references/material-traps.md](references/material-traps.md)：材质排错记录。
- `evals/evals.json`：Agent 行为验收场景，不是自动执行的测试套件。

## 环境要求

- 宿主 Python：建议 3.11 或更高，安装 Pillow、NumPy。
- Blender：原流程使用 Blender 5.x；需要能够运行 EEVEE 的图形环境。
- PMX 导入扩展：当前脚本调用 `bpy.ops.mmd_tools_local.import_model`。必须在所使用的 Blender 配置中安装并启用提供此操作符的扩展；普通 `mmd_tools` 的命名可能不同，需要检查并适配两个 Blender 脚本。扩展未随本仓库分发，本仓库不提供自动安装器。
- Blender 自带 Python 需要可导入 NumPy；`bpy` 和 `mathutils` 由 Blender 提供，不要在宿主 Python 中直接运行两个 Blender worker。
- 拼版需要可显示中文的字体文件，可用 `--font` 和 `--font-bold` 指定。

## 快速开始

在仓库根目录执行：

```powershell
python -m pip install -r requirements.txt
```

将模型和贴图按以下方式放置，保留模型包内部的相对路径：

```text
models/
  CharacterA/
    CharacterA.pmx
    textures/
  CharacterB/
    CharacterB.pmx
    textures/
```

先验证一个角色。下面的 Blender 路径和角色名需要替换为实际值：

```powershell
python scripts/run_all.py --root models --out out/three_views --blender "<blender-executable>" --only CharacterA
```

人工检查脸部、裙摆、透明层和轮廓后，再批量执行：

```powershell
python scripts/run_all.py --root models --out out/three_views --blender "<blender-executable>" --res 1600x2000
python scripts/assemble_sheets.py --root out/three_views --font "<regular-font-file>" --font-bold "<bold-font-file>"
python scripts/check_views.py --root out/three_views
```

字体参数接受字体文件路径；Windows 也可使用 `--font-dir` 指向系统字体目录，默认查找 `msyh.ttc` 和 `msyhbd.ttc`。

每个角色输出 `front.png`、`side.png`、`back.png`、`_render_report.json`，以及拼版后的 `<角色>_三视图.png`。默认单图为 **1600×2000**，拼版为 **5040×2400**。总览在至少两个角色参与拼版时生成。

人工确认结果后冻结基准；后续修改必须使用同样的分辨率重新渲染，再比较：

```powershell
python scripts/baseline_guard.py save --root out/three_views --baseline out/baseline
python scripts/baseline_guard.py check --root out/three_views --baseline out/baseline --strict
```

基准目录必须是新目录。严格检查出现回归或缺图时返回非零退出码。若修改输出尺寸，应先重新验收并建立新的基准。

## 使用范围与限制

- 这是现有模型的工程视图导出流程，输出保留模型的形状和比例；不包含重新设计、补建模或自动修复模型。
- 渲染脚本支持 `--res`，但当前拼版脚本固定要求 1600×2000。
- 模型选择采用文件名和大小启发式；每个角色应使用唯一目录名，并检查日志里选中的 PMX。
- 当前渲染 worker 使用 EEVEE，没有自动切换 Workbench / Cycles 的功能。
- 自动检查不能证明颜色、造型或材质正确，仍需逐图目视检查。基准检查只比较已收录的视图，新增角色应另行验收。
- 报告和 `_jobs` 中会包含运行时的模型路径；这些文件默认被 Git 忽略，分享时应另行检查。
- 文档中的 VERIFIED / FIXED 是提炼时记录的历史证据状态，不代表所有模型、Blender 版本或硬件环境都已验证。

## 作为 Agent Skill 使用

将本仓库作为一个完整的 `pmx-three-views` 技能目录放入所用 Agent 支持的技能位置，或直接让 Agent 阅读 [SKILL.md](SKILL.md)，并提供模型目录、输出目录、Blender 路径和交付要求。保持 `scripts/`、`references/` 和 `evals/` 与 `SKILL.md` 的相对位置。

## 发布检查

本次发布检查包括技能静态校验、敏感信息扫描、六个 Python 脚本语法检查、四个宿主 CLI 的帮助入口，以及合成图片的质检和基准回归检查。本次发布没有重新执行真实 PMX / Blender 渲染；历史使用记录见 [证据说明](references/evidence.md)。

## 许可证与素材

本仓库代码和文档使用 [MIT License](LICENSE)。Blender、PMX 导入扩展、Python 依赖及字体分别遵循其自身许可证。

仓库只包含工具和方法文档，不包含角色模型、贴图、字体、Blender 或扩展源码。使用和分享模型及渲染图时，请遵守各自素材的授权条件。
