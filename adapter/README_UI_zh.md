# ArcGIS Pro 可交互原型

在 ArcGIS Pro 的 Catalog 中添加 `AreaRankingAudit_UI.pyt`。保留它旁边的旧 `AreaRankingAudit.pyt`，并保留 `adapter`、`build`、`core` 三个目录的相对位置。旧工具箱继续可用。可交互版运行时会自动保存 JSON，供复现和之后重复使用；不需要手写配置文件。

## 构建指标

选择候选点、区域面，再选各自 ID 字段。空间指标逐行选择来源图层、名称、计算方法、半径、去重字段、覆盖是否已知和理由。计数的半径填米；最近距离的半径填 `-`。不使用去重字段或没有理由时也填 `-`。对已有测量，在 Measurement table 选择来源表，再用 ID field in measurement table 指定关联字段。来源表中有同名候选 ID 时会自动带出。Choose numeric fields 提供多选列表；Import all eligible numeric fields 批量导入并提示字段清单。每列沿用源字段名。工具按字段类型、ID 和输出命名规则筛选；若年份、坐标、编码等数值列混在测量表中，请用多选指定要分析的列。要改名或合并多来源测量，可展开 Custom mappings 逐条映射。来源为空且覆盖未知时不会把它当作 0。输出 CSV 旁自动保存来源、计算方式和理由。

构建指标表中的可选值可用 `-` 表示不使用。审查排名中的 Minimum、Maximum 可直接留空，填写 0 会作为数值门槛保留。去重字段和来源表字段当前需要手填字段名；不能声称已完成每一行随图层变化的字段联动。不同投影、几何和数据质量的约束见 `../build/README_zh.md`。

## 审查排名

选择指标 CSV、候选点 ID 和区域 ID，再逐行选指标字段、方向、权重；Minimum、Maximum 留空时表示不设对应的硬门槛。权重合计必须为 1。默认从输入的全部计划点拟合 P5/P95：每个指标分别使用该列有效值，不先筛共同完整点。运行后保存 `reference.json`；调整权重或比较不同区域时，选 **Use saved reference JSON** 并指定它，避免重新拟合。也可以选择单独的参考 CSV。

还可选择区域多边形、另一份样本、覆盖和可行比例、前 K、低样本门槛及权重敏感性。对其他分区的样本，以共同点 ID 比较；缺少共同 ID 时不能计算该对照。结果中的 `run_configuration.json` 保存设置和参考来源，`reference.json` 保存实际参考参数。

## 实测和限制

ArcGIS Pro 3.5.1 的 ArcPy 实测了多行配置、含空格的路径、`-` 占位、全部计划点参考、单独参考和保存参数复用。21 个合成点的计数及距离构建成功，排名 A/C/D/E/F、共同点 Jaccard 9/11 与考题答案一致，调整权重后冻结的参考参数不变。此为 ArcPy 调用测试，尚未确认 Pro 图形界面的每个下拉和交互细节，不能声称已经完成第二台机器或 `.gpkx` 验收。空间计算只测过小样例；路网计算仍由外部提供。

## 在地图中复核候选区

在 Catalog 刷新界面版工具箱，再打开 Audit Area Rankings。填写 Region polygons 和 Polygon region ID field 即可输出区域地图。用合成案例时选择 示例数据/地图验收/boundaries.gdb 中的 regions，区域 ID 选 region。每次运行都会在结果目录的 results.gdb 中写入 region_audit 表，提供边界时另有 ranked_regions 面和 Ranked regions.lyrx 分类图层。Pro 是否把输出加到当前地图取决于地理处理的输出显示设置。可用 Map → Add Data 直接添加 .lyrx 查看图例。

按 ARA_top = 1 选择入选区。点开区域查看 ARA_rank、ARA_plan、ARA_valid、ARA_cover 和 ARA_low，再与候选住宅叠加。橙色标记入选且可行点低于样本量门槛的区；灰色标记有计划点但未达资格的区。ARA_score 是可行点均分，资格和名次需分别看 ARA_elig 和 ARA_rank。

工具 1 成功输出 CSV 后，会自动将它加入当前地图的 Contents → Standalone Tables。同一路径已在图中时复用已有表。需在 Pro 内打开地图运行。没有可用地图或添加失败时，工具会显示警告，CSV 仍保存在所选位置。

## 地图样式和候选点

区域面按前 K、后续 45 名、之后 50 名和剩余名次分层。前 K 中样本量低于设定门槛的区域使用橙色，其余使用绿色，其他合格区域按排名显示蓝色层级。无计划点和不合格区域单独着色。只标注前 K 的名次及名称，区域面有 area_name 字段时使用 area_name，否则使用区域 ID。

如需同时输出候选点，在工具 2 的 Candidate point layer for map 选择候选点，Candidate point ID field 选择与指标表 ID 对应的字段。工具输出 Audited points.lyrx 和 results.gdb/audited_points：蓝色点表示满足硬条件，红色点表示测量不完整，橙色点表示未满足硬条件。点位在地图比例尺放大到 1:60,000 后显示。候选点图层必须覆盖全部计划点 ID；重复或缺失 ID 会报错。未选择候选点图层时，工具仍生成区域图层。

工具 2 选用工具 1 输出的 CSV 时，会尝试读取同目录、同名的 _indicators.json，并自动填写 Candidate point layer for map 和点 ID 字段。自动填写使用记录的真实来源路径，来源路径有效且为点图层时生效；分析师仍可手动修改。更换数据后没有来源记录时，直接手动选择点图层即可。
