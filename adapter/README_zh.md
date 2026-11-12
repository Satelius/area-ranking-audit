# ArcGIS Pro 工具箱原型

在 ArcGIS Pro 的 Catalog 中添加 `AreaRankingAudit.pyt`。保持 `adapter`、`core` 和 `build` 三个文件夹为同级；本原型从相邻文件夹加载代码。已在本机 ArcGIS Pro 3.5.1 的自带 Python 中通过 ArcPy 工具调用验证，界面交互、第二台机器和 gpkx 打包尚未验证，暂不宜公开发布。

## 工具 1：Build Indicators

输入候选点、地区多边形、各自的 ID 字段名、指标定义 JSON，以及尚不存在的输出 CSV 路径。候选点必须是以米为单位的投影坐标，每个点须恰好落入一个区域；跨区域边界、重复 ID 和未知坐标系会报错。设施来源为空且覆盖情况未知时按缺失处理；只有明确声明覆盖已知时，附近零个设施才是有效零。设施计数、最近设施和按候选点 ID 接入已有表的格式见 `build/README_zh.md`。其中 `data` 是本机 ArcGIS 图层或表路径，`table` 方法需设置 `value_field` 和表内 `id_field`。这一步的全量性能尚未验证。

## 工具 2：Audit Area Rankings

输入工具 1 的 CSV、配置 JSON、参考样本 CSV 或已冻结的参考参数 JSON（二选一）、现有输出父目录。若 CSV 的候选点 ID 或区域 ID 字段不是 `point_id` / `area_id`，使用 `id_fields` 指定原列名。每次运行都在父目录建立唯一的新文件夹。可选输入区域多边形和其 ID 字段，生成带 `ARA_` 排名字段的 `results.gdb/ranked_regions`；多边形中没有样本的区域不计分。提供第二份 CSV 时使用相同指标和参考参数再评分：勾选同一地区 ID 才按地区名比较，否则按共同点 ID 比较；没有共同点时会明确标明无法比较。

配置 JSON 示例：

```json
{
  "criteria": [
    {"name":"clinic_count", "direction":"benefit", "weight":0.5},
    {"name":"road_km", "direction":"cost", "weight":0.5, "max":20}
  ],
  "id_fields": {"point_id":"point_id", "area_id":"region"},
  "settings": {"coverage":0.9, "feasible":0.5, "low_n":3, "top_k":5},
  "sensitivity": {"enabled":true, "draws":1000, "seed":42, "concentration":50}
}
```

权重必须和为 1。`max` 是可选硬门槛，此处表示超过 20 公里的点不满足条件。标准化参考 JSON 每项保存 `p5`、`p95`；参考 CSV 中必须有各指标字段。本工具不从地址或路网计算驾车路线，需提供已有测量表。启用敏感性分析要求至少两项指标且每项基线权重均大于 0。

输出包括：地区和点的 CSV、区域空间图层（如提供边界）、`audit.json`、`reference.json`、`run_configuration.json`、HTML 报告，以及选用时的 `sensitivity.json` 和 `comparison.json`。区域报告显示前 K 的平均指标贡献；单因素变化数量是相对于基线前 K 的集合比较。蒙特卡罗频率只代表所设权重分布下的频率，不是现实适宜性的概率；敏感性不能证明指标选择合理。

## 实测

用 `test_adapter.py` 和 ArcGIS Pro 自带 Python 实测工具箱加载、两工具调用及衔接。考题得到 A/C/D/E/F 前五、B 区 8/10 共同覆盖被排除、跨分区共同点 Jaccard 9/11，并生成 GDB 图层、报告、参数及敏感性输出。Build 工具在 21 个合成点上计算设施计数和到面距离，再将结果交给 Audit。测试只证明这一合成案例及接口路径，不证明大规模数据、各种几何、地图符号样式或打包发布已经通过验收。
