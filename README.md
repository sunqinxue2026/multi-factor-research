# 基于 Python 的多因子选股与量化策略研究系统

Python Multi-Factor Stock Selection and Research System

面向量化开发学习与求职展示的分阶段研究项目。目标链路为：行情整理 → 因子 → 横截面预处理 → IC/RankIC与分组 → 综合评分 → 定期选股 → 回测适配 → 研究报告。

**第一至第七阶段已验收；第八阶段未开始。本仓库尚非完整可执行策略或盈利模型。**

当前还已实现三个基础因子、横截面预处理、未来收益标签、IC／RankIC、分组统计及多因子目标计划，详见各阶段章节。目标计划不等于包含费用与成交约束的组合回测。

## 已实现

- 兼容项目一八列行情格式，支持多股票CSV、股票代码前导零、联合键唯一及OHLC数值校验。
- 记录来源、复权口径、单位、数据截至日期和原文件SHA-256。
- 使用显式交易日历构造股票×日期面板；保留缺失价格，不自动填充行情。
- 区分真实零值、缺失记录和未知上市／停牌状态；支持逐日状态Python接口及横截面查询。
- 命令行导出面板和运行摘要，拒绝覆盖已有输出目录。

## 快速运行

最低兼容目标为Python 3.10；当前前两阶段已在Python 3.10.11及此前Python 3.12.14环境验证。3.10实测依赖为Pandas 2.3.3、NumPy 2.2.6、pytest 8.4.2；不代表全部版本组合均通过。以下命令在Windows项目根目录运行：

```powershell
git clone https://github.com/sunqinxue2026/multi-factor-research.git
cd multi-factor-research
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -I -X utf8 -m pytest -o pythonpath=src -p no:cacheprovider -q
.venv\Scripts\python.exe -I -X utf8 scripts/prepare_data.py --csv data/test/synthetic_market.csv --metadata data/test/synthetic_metadata.json --calendar data/test/synthetic_calendar.csv --calendar-source synthetic/calendar --calendar-version v1 --output reports/my_first_run
```

安装命令供使用者创建独立环境；不代表本次在新环境中完成依赖安装验证。每次演示使用不同输出目录，例如`reports/my_second_run`。

### 样例预期

仓库样例是明确标注的合成数据和合成日历，不是真实证券数据。

| 股票 | 2025-01-02收盘 | 2025-01-03收盘 | 2025-01-06收盘 |
|---|---:|---:|---:|
| 000001 | 11 | 缺失 | 13 |
| 000002 | 20 | 21 | 缺失 |

4条行情、2只股票、3个日历日生成6行面板，其中2条缺失记录；4条原始行情的真实可交易性仍未知。0成交量不等于缺失，不自动认定停牌。输出为`panel.csv`和`summary.json`，生成产物不提交Git。

## 输入契约

行情CSV必须包含：

```csv
symbol,trade_date,open,high,low,close,volume,amount
```

- 股票代码为字符串，日期使用YYYY-MM-DD；价格须为有效正数，成交量／额非负，允许真正缺失值。
- 单位为CNY／股／CNY，不自动换算；价格口径必须声明未复权、前复权或后复权。
- 重复股票日期键、非法字符串数值及错误OHLC关系直接报错，不静默去重。
- 日历CSV仅含`trade_date`列，明确列出市场开放日期；不会用普通工作日替代交易日历。
- 来源JSON字段及样例见[data/test/synthetic_metadata.json](data/test/synthetic_metadata.json)。

## 源码阅读顺序

1. [data.py](src/multi_factor_research/data.py)：元数据契约、行情检查、显式日历、面板与横截面。
2. [prepare_data.py](scripts/prepare_data.py)：参数、日志、结果导出和运行摘要。
3. [test_data.py](tests/test_data.py)：手工数值、缺失／零值、状态边界及历史不变性验证。

## 开发阶段

| 阶段 | 内容 | 状态 |
|---|---|---|
| 1 | 架构、数据结构、因子公式和计划 | 已验收 |
| 2 | 数据读取、整理和交易日历 | 已验收 |
| 3 | 动量、波动率、均线偏离因子 | 已验收 |
| 4 | 截尾、标准化和方向统一 | 已验收 |
| 5 | IC、RankIC及分组分析 | 已验收 |
| 6 | 多因子评分及定期调仓 | 已验收 |
| 7 | 项目一回测接口适配 | 已验收 |
| 8 | 可视化、完整验证和研究报告 | 未开始 |

第三阶段使用历史窗口计算因子，第四阶段按同日截面处理；未来收益标签与评分隔离。项目一当前为单股票引擎，第七阶段在项目二新增独立多股票共享现金执行适配层，未修改项目一，不能通过平均单股收益替代组合执行。

## 测试与边界

第二阶段已有41项pytest通过记录，具体环境和本次仓库发布验证见[开发进度](docs/开发进度.md)。测试覆盖具体值，而非仅判断不报错；追加未来数据的历史不变性仅针对已覆盖案例，不代表全部系统不存在前视偏差。

当前已有研究性IC、分组分析、调仓目标计划、独立组合执行适配层和组合绩效计算；尚未接入项目一数据库、Matplotlib图表或网页功能；MySQL、SciPy、Matplotlib属于后续计划，不是当前已实现依赖。执行层使用合成行情演示共享现金、费用、整手和T+1，未验证真实多股票数据及权威日历。没有历史股票池和退市数据，不能宣称消除幸存者偏差。状态未知不等于可成交；文件摘要不证明数据真实或历史可获得性。

## 中文文档

- [开发计划](docs/开发计划.md)
- [开发进度](docs/开发进度.md)
- [总体设计与公式](docs/第一阶段_总体设计.md)
- [第二阶段验收](docs/第二阶段_数据读取与交易日历验收.md)
- [技术决策](docs/技术决策.md)
- [面试知识整理](docs/面试知识整理.md)

仓库仅提交源码、测试、合成教学数据、依赖和文档；不提交虚拟环境、IDE配置、数据库、运行报告、真实行情或凭据。每阶段独立验证，负责人验收后再推进。

## 第三阶段：基础因子（已验收）

新增[因子模块](src/multi_factor_research/factors.py)、[24项因子测试](tests/test_factors.py)和[合成演示入口](scripts/calculate_factors.py)。支持20/60及自定义N≥2窗口：动量使用N+1个连续有效收盘；波动率使用N个日收益样本标准差；均线偏离保留原始符号。状态保留，valid不是可投资资格。

```text
python -I -X utf8 scripts/calculate_factors.py --windows 3 --output reports/stage3_hand_run
python -I -X utf8 scripts/calculate_factors.py --output reports/stage3_default_run
```

输出为factors.csv与summary.json，目录已存在时拒绝覆盖。入口只生成两只虚构证券的80日教学样本，不是任意CSV导入入口；实际面板通过calculate_factors API接入。

本阶段最终全量65项通过：Python3.10.11/Pandas2.3.3/NumPy2.2.6/pytest8.4.2，pip check通过；另在3.12.14/Pandas3.1.1/NumPy2.5.4/pytest9.2.0通过。后者NumPy超出声明范围，只是额外环境证据，不代表声明内3.12依赖矩阵验证。详细失败修复、手算及限制见[第三阶段验收](docs/第三阶段_基础因子实现与验收.md)。

## 第四阶段：因子预处理（已验收）

[预处理模块](src/multi_factor_research/preprocessing.py)按日期、因子和窗口分组：默认1%/99%线性分位数截尾、至少5只、ddof=0 Z-score，动量+1/波动率−1/偏离−1。明确停牌或未上市排除，未知状态保留并审计，不代表可投资。少样本和零方差输出无效，不填0。原始值与原因保留。

```text
python -I -X utf8 scripts/preprocess_factors.py --output reports/stage4_my_run
python -I -X utf8 scripts/preprocess_factors.py --windows 3 --no-clip --output reports/stage4_no_clip_run
```

入口生成8只虚构证券的80日教学数据，输出preprocessed_factors.csv、cross_section_audit.csv、summary.json；拒绝覆盖目录。真实因子通过preprocess_factors API传入。默认演示640条行情、3840行因子、480截面、1936行预处理有效；不是收益证据。

本轮全量95项测试通过（新增30项）：Python3.10.11/Pandas2.3.3/NumPy2.2.6依赖安装和pip check通过；Python3.12.14/Pandas3.1.1/NumPy2.5.4也通过，但此NumPy超出声明范围，仅为额外验证。导出242个有效截面均值近0、总体标准差近1，审计计数及两环境Z-score一致。详见[第四阶段验收](docs/第四阶段_因子预处理与标准化验收.md)。此为第四阶段历史证据；第五阶段状态见下节，当时评分、组合或回测适配尚未实现；当前目标计划进度见第六阶段。

## 第五阶段：因子评价（已验收）

[分析模块](src/multi_factor_research/analysis.py)提供下一开盘至H日后开盘标签、原始/定向值Pearson IC和平均秩RankIC、非年化ICIR、五组/十组收益及风险汇总。分组先按当日因子确定成员，缺标签整组无效；累计采用固定锚点非重叠区间，预热后缺口阻断。不是可执行组合收益，也不提供有效alpha结论。

```text
python -I -X utf8 scripts/analyze_factors.py --windows 20 60 --horizons 5 20 --groups 5 --output reports/stage5_my_run
```

输出五类评价CSV、标签CSV及summary.json；目录必须未存在。演示为15只虚构证券、100个教学日期：1500行情、3000标签/2595有效、2400 IC记录/1124有效、6000分组/2810有效、60组风险汇总。累计值挂在信号日但到exit_date才实现，不能用作当日已知净值。图表绘制留第八阶段。

本阶段全量118项通过：Python3.10.11/Pandas2.3.3/NumPy2.2.6/pytest8.4.2及当前3.12环境；声明内依赖和pip check证据来自3.10。新增23项，包含手算、并列、时序、非重叠及缺口。详见[第五阶段验收](docs/第五阶段_因子有效性与分组分析验收.md)。

## 第六阶段：多因子评分与调仓计划（已验收）

前三因子默认20日、定向值各1/3，全部有效才评分；Top5可配置，同分按代码；每只1/N、不足留现金。周/月末信号，下一显式交易日计划执行，日历尾部未确认周期跳过。显式记录退出、现金及含现金的目标单边换手。**这是目标计划，不是实际持仓、成交换手或策略收益**；费用、滑点及共享现金执行留第七阶段。

```text
python -I -X utf8 scripts/plan_portfolio.py --output reports/stage6_my_run
python -I -X utf8 scripts/plan_portfolio.py --frequency monthly --output reports/stage6_my_monthly
```

目录必须未存在。输出scores.csv、target_weights.csv、target_changes.csv、rebalances.csv及summary.json。15只虚构股票、100个工作日教学位置，非权威交易所日历：1500行情、1500评分/1200有效；周20次计划/4次全现金，月4次/0次全现金。不使用未来收益标签选股。

本阶段实际全量146项测试（新增28项）在Python3.10.11/Pandas2.3.3/NumPy2.2.6及Python3.12.14/Pandas3.1.1/NumPy2.5.4通过；3.12的NumPy超声明范围，仅额外证据，3.10依赖安装及pip check通过。导出权重、换手、时序和两环境评分核对通过。详见[第六阶段验收](docs/第六阶段_多因子组合与定期调仓验收.md)。第七阶段当前状态见下节。


## 第七阶段：组合执行与绩效串接（已验收）

新增`execution.py`、`performance.py`、`execute_portfolio.py`、`run_stage7.py`及对应测试。`run_stage7.py`已将数据整理、20日因子、预处理、等权Top5评分、周调仓、共享现金执行和组合绩效串成一个可运行入口。

```text
python -I -X utf8 scripts/run_stage7.py --output reports/stage7_my_run
python -I -X utf8 scripts/execute_portfolio.py --output reports/stage7_execution_only
```

完整演示使用15只合成证券和100个教学交易日，输出1500条行情、1500行评分、1200行有效评分、20次调仓、41笔订单和41笔成交。绩效模块沿用项目一的首日收益、峰值回撤、年化收益、年化波动率和夏普公式，但不使用项目一仅适用于单股票完整买卖配对的胜率统计。合成数据结果不代表策略有效性。

本阶段全量152项测试已在当前环境通过；Python 3.10.11独立环境安装声明依赖、`pip check`、全量152项测试和完整入口均通过。第七阶段未接入项目一数据库、Matplotlib图表或网页，也未建模涨跌停、停牌撮合、公司行动、历史股票池和真实交易。详见[第七阶段验收](docs/第七阶段_项目一回测接口适配与组合执行验收.md)。
