![Area Ranking Audit — 区域排名与证据审查](assets/area-ranking-audit-banner.png)

# Area Ranking Audit：ArcGIS Pro 区域排名审查工具

[English](README.md)

**资格**：以全部计划点为分母，完整测量和满足硬条件的点比例均达标，区域才获准参与排名。

**让每个推荐亮出证据：多少样本撑起高分，换个假设谁会出局。**

这个工具帮助分析师先计算候选点的指标，再检查区域排名背后的样本证据。它起源于 [GE5219 住宅可达性项目](https://github.com/Ranyix0302/5219finalproject)，也支持用户自行定义指标和区域。工具实现的是可复用分析流程，并未宣称提出新的空间排序算法。

## 两个工具做什么

1. **Build Indicators（构建指标）**：将计划候选点归属到区域；计算指定半径内设施数量、到最近设施的直线距离，或者用候选点 ID 关联已有数值。已有测量字段可多选或批量导入。输出 CSV 可自动加入当前地图的独立表。
2. **Audit Area Rankings（审查区域排名）**：设置指标方向、权重和可选上下限，判断区域资格后排序。输出报告与明细表；提供区域边界时还会生成带样式的排名图层，可选生成候选点状态图层。

**区域分母始终是全部计划点。**完整覆盖要求同一个点的所有必需指标均有值。默认门槛是至少 90% 的计划点完整、至少 50% 的计划点满足硬条件；可行点少于 3 个时提示低样本。这些都是可调整的项目假设，不是普适标准。

各指标使用参考样本的第 5、95 百分位数标准化。比较权重或筛选后的结果时，应保存并复用参考参数。可选的单因素和蒙特卡罗权重敏感性分析显示假设变化带来的排名变化；模拟进入前 K 的频率不代表区域真实适居概率。不同样本或分区可通过共同点 ID 比较。

## 环境与安装

- 需要 ArcGIS Pro、ArcPy 和相应的 Esri 授权。本机已测试 **ArcGIS Pro 3.5.1**，尚未完成第二台电脑的独立测试。
- **使用打包版**：下载 [Area_Ranking_Audit.gpkx](dist/Area_Ranking_Audit.gpkx)，在 ArcGIS Pro 使用 **Extract Package** 解包，然后在 Catalog 中添加解包后的 `p30/adapter/AreaRankingAuditRelease.pyt`。
- **使用源码版**：下载仓库，在 Catalog → Toolboxes → Add Toolbox 添加 `adapter/AreaRankingAudit_UI.pyt`。请保持 `adapter`、`build`、`core` 的相对目录不变；UI 工具箱旁边的旧版工具箱是运行依赖。

打包版内含合成数据；解包后的 `commondata/synthetic.gdb` 内有 `candidates`、`regions` 和 `measurements`。源码版的 `examples/` 提供合成 CSV 与 GeoJSON，使用空间工具前请导入或转换为 Pro 可用的要素类。

## 使用合成案例

1. 运行 **Build Indicators**。选择打包数据的 `candidates` 点和 `regions` 面，ID 字段分别选 `point_id`、`region`。在已有测量部分选择 `measurements`，用 `point_id` 关联，并选择 `indicator_1`、`indicator_2`；将输出 CSV 保存为一个尚不存在的文件名。
2. 运行 **Audit Area Rankings**。选择刚输出的 CSV；候选点 ID 为 `point_id`，区域 ID 为 `region`。两个指标均设为 **Higher is better**、权重各为 **0.5**，Minimum 和 Maximum 留空。标准化参考选 **Use separate reference CSV**，选择包内的 `reference_sample.csv`；选择一个可写的输出父文件夹。
3. 要生成地图，在 Region polygons 选择 `regions`，区域 ID 选择 `region`；可选地选择 `candidates` 和 `point_id` 生成候选点图层。运行后，如果排名图层没有自动加入地图，从结果文件夹打开 `Ranked regions.lyrx`。

预期前五是 **A、C、D、E、F**。A 排名第一，但只有一个点，会标记低样本。B 的两个指标分别覆盖 10 个计划点中的 9 个，但缺失点不同，因此共同完整覆盖只有 8/10，低于 90%，不进入排名。详见[合成案例与手算](examples/README_统一考题.md)。

## 输出与解读

结果目录包含 HTML 报告、点和区域 CSV、运行配置及保存的参考参数。提供区域边界后会生成 `results.gdb/ranked_regions` 和 `Ranked regions.lyrx`；提供候选点还可生成 `audited_points` 和对应图层。区域得分是可行点的平均分，使用时应同时查看资格、样本数量和覆盖率。无资格或未测量区域不能视作低分合格区域。

## 方法边界

- 计数和直线距离依赖数据覆盖、几何质量与合适的投影坐标系。直线距离不等于路网步行时间。
- 工具不计算驾车路线，也不将学校地址转为驾车距离。请将外部计算的路线结果作为数值字段导入；未找到路线应保留缺失。
- 固定参考参数有助于比较，但指标定义、参考样本、硬约束和采样方式变化都会影响结果。敏感性分析不能证明指标在概念上合理。
- 开源代码不包含 ArcGIS Pro 授权。仓库不包含 GE5219 真实原始数据；示例为合成数据。

## 文件结构

- `adapter/`：交互版和旧版 Python 工具箱。
- `build/`：指标构建代码与测试。
- `core/`：区域资格、评分及敏感性计算。
- `examples/`：合成数据及手算答案。
- `dist/`：ArcGIS 地理处理包。

## 许可与致谢

代码和合成示例采用 [MIT 许可证](LICENSE)。工具由 GE5219 小组项目中的工作发展而来。ArcGIS、ArcGIS Pro 为 Esri 产品，使用受其自身条款约束。
