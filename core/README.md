# Area Ranking Audit 计算核心

`area_audit.py` 使用 Python 标准库，不依赖 ArcGIS；Python 3.9 及以上可运行。每个候选点是一个字典，包含 `point_id`、`area_id` 和每项指标字段，缺测值以空值表示；缺少指标字段、重复或空 ID 会报错。

每项指标配置例子：`{'name': 'clinic_count', 'direction': 'benefit', 'weight': 0.2, 'min': 1}`。`direction` 可以为 `benefit` 或 `cost`；`min`/`max` 为原始数值硬约束，均可省略；权重非负且和为 1。

1. `fit_reference(reference_rows, criteria)` 拟合 P5/P95，输出可序列化字典；有效观测不足以提供不同的 P5/P95 时拒绝运行。
2. `audit(rows, criteria, reference, coverage=.9, feasible=.5, low_n=3, top_k=5, tiebreak=None)` 使用固定参考计算逐点、区域结果。区域分母包含全部计划点。阈值和 Top K 可以更改；默认用区域 ID 对完全同分的区域排序。可传入指标字段列表 `tiebreak`，按可行样本的原始值均值及指标方向依次解并列。输出包含逐点的缺失字段、约束、原值、标准分、权重贡献与区域计数、资格、分数、排名。
3. `weight_sensitivity(rows, criteria, reference, draws=1000, seed=42, concentration=50, oat_values=None, **audit_options)` 在固定参考上返回 OAT 和蒙特卡罗权重及前 K 集合。为防止 Dirichlet 退化，当前敏感性分析要求至少两项且所有基准权重均大于零。`seed` 使用 Python `random.Random` 的 Gamma 抽样；其序列不会逐次匹配早期使用 NumPy 的实验。频率只适用于指定权重分布，不是现实概率。
4. `compare_rankings(first, second, same_units=False)` 比较两个 audit 返回值。相同单位设置 `same_units=True`，按前 K 区域 ID 比较；不同单位按双方共同点 ID 的入选区域覆盖集合比较。没有共同 ID 或并集为空返回无法比较的明确状态；比较范围是共同点，不自动代表总人口或全部住房。

用 `python -m unittest -v` 检查合成考题。`python verify_ge5219.py <仓库路径>` 回放已冻结的 B 点与参数，并验证原来的区域资格、分数及排名；这不是独立核实路网、设施数据或 ArcGIS 界面的证据。回放结果在 `ge5219_baseline_verification.json`。
