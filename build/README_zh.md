# 构建原始指标表：原型说明

`arcpy_indicators.py` 可以在 ArcGIS Pro 自带的 Python 中运行，不依赖 GeoPandas。函数 `build_arcpy_indicators(candidates, regions, specs, output_csv, id_field='candidate_id', region_field='region_id')` 将每个计划候选点写成 CSV 的一行，附区域 ID、指标原始值和 `<指标名>__status`。输出文件必须不存在，避免意外覆盖。

参数示例（数据集路径需换成实际地理数据库、图层或 ArcGIS 支持的表）：

```python
specs = [
    {'name': 'bus', 'method': 'count_within', 'data': bus_layer,
     'radius_m': 800, 'coverage_known': True, 'deduplicate_by': 'stop_id'},
    {'name': 'park', 'method': 'nearest', 'data': park_polygon_layer,
     'coverage_known': True},
    {'name': 'campus_drive_km', 'method': 'table', 'data': route_table,
     'id_field': 'candidate_id', 'value_field': 'distance_km'},
]
build_arcpy_indicators(candidate_layer, region_layer, specs, 'new_indicators.csv')
```

`count_within` 对点设施计数，包含圆周边界；`nearest` 使用到点或面最近位置的平面距离，单位米；在面内为零。已测量的学校道路里程用 `table` 按候选 ID 关联，原单位由使用者记录；本工具不请求路线、不把直线距离冒充道路距离。额外指标只需增加一条规则，例如把 `bus` 换成 `restaurant` 并提供餐厅点图层。

空间指标的 `coverage_known=True` 表示使用者已确认来源覆盖本次研究范围；否则全列为空并标 `coverage_unknown`。已知覆盖下，空设施图层的计数为 0；最近设施距离则为空并标 `no_facilities`。表中没有该候选 ID 或值为空时标 `missing_measurement`，不会替换成零。可选的 `deduplicate_by` 以设施 ID 去重，同 ID 几何不一致时报错，避免悄悄丢数据；未指定时每条要素计一次。

候选必须为米制投影坐标的点，分区必须为多边形；无 CRS、空几何、重复或空候选 ID 都报错。点必须恰好与一个区域相交：区域外点、落在共有边界或区域重叠上的点直接报错，请先按项目规则解决，不能私自挑一个区。不同地理基准的输入要在运行前明确使用正确地理转换；不自动选择转换。

本 ArcPy 原型逐点逐设施计算距离，复杂度随候选点与设施数相乘增长，仅在小型合成数据验证过；投入全量数据前须采用空间索引或 ArcGIS 近邻/空间连接工具并测试性能。尚未验证所有数据格式、几何有效性、许可版本和极端规模；CSV 不保留点几何，应按稳定候选 ID 连回原图层。来源、单位、选用理由和数据覆盖依据需要由使用者另行保存。

`indicators.py` 是可独立于 ArcGIS 使用的 GeoPandas 版本，接口一致但接收内存数据框并返回 GeoDataFrame。它需要 geopandas、shapely、numpy、pandas；不要直接修改 ArcGIS Pro 默认 Python 环境以安装这些包。

验证：在本机 ArcGIS Pro 3.5 环境运行 `python test_arcpy_indicators.py`；在具备 pytest 和 GeoPandas 的环境运行 `python -m pytest -q test_indicators.py`。测试使用临时合成数据，不修改项目原始数据。Windows 可能因 ArcGIS 文件锁残留临时测试文件。
