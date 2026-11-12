# 基于 Python 的多因子选股与量化策略研究系统

Python Multi-Factor Stock Selection and Research System

面向量化开发学习与求职展示的分阶段研究项目。目标链路为：行情整理 → 因子 → 横截面预处理 → IC/RankIC与分组 → 综合评分 → 定期选股 → 回测适配 → 研究报告。

**第一至第三阶段均已由负责人验收通过；第四至第八阶段尚未实现，不能将本仓库视为完整多因子策略或盈利模型。**

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
| 4 | 截尾、标准化和方向统一 | 未开始 |
| 5 | IC、RankIC及分组分析 | 未开始 |
| 6 | 多因子评分及定期调仓 | 未开始 |
| 7 | 项目一回测接口适配 | 未开始 |
| 8 | 可视化、完整验证和研究报告 | 未开始 |

第三阶段预计使用历史窗口计算因子，未来收益标签与评分隔离。项目一当前为单股票引擎，多股票共享现金组合仍需接口评审，尚未接入，不能通过平均单股收益替代。

## 测试与边界

第二阶段已有41项pytest通过记录，具体环境和本次仓库发布验证见[开发进度](docs/开发进度.md)。测试覆盖具体值，而非仅判断不报错；追加未来数据的历史不变性仅针对已覆盖案例，不代表全部系统不存在前视偏差。

尚无IC、调仓、数据库写入、回测或网页功能；MySQL、SciPy、Matplotlib属于后续计划，不是当前已实现依赖。未验证真实多股票数据及权威日历。没有历史股票池和退市数据，不能宣称消除幸存者偏差。状态未知不等于可成交；文件摘要不证明数据真实或历史可获得性。

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
