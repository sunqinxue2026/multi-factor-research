# 基于 Python 的多因子选股与量化策略研究系统

Python Multi-Factor Stock Selection and Research System

一个支持多股票日频行情、因子研究和组合历史模拟的 Python 系统。提供中文网页工作台和命令行入口，输出研究图表、交易明细、静态 HTML 报告及可下载的研究结果。

## 功能概览

| 功能 | 当前支持 |
|---|---|
| 数据整理 | 多股票 CSV、来源元数据、显式交易日历、字段与价格校验、缺失记录保留 |
| 基础因子 | 动量、日收益波动率、均线偏离；默认20日窗口 |
| 因子预处理 | 同日截面1%/99%分位数截尾、Z-score、因子方向统一、处理审计 |
| 因子评价 | IC、RankIC、分组收益、高低组收益差、非重叠区间统计 |
| 组合计划 | 等权或自定义因子权重、排名、Top N、周/月调仓、目标变化 |
| 历史模拟 | 多股票共享现金、先卖后买、整手、T+1、佣金、税费、滑点及拒单记录 |
| 绩效与报告 | 净值、收益、回撤、波动率、夏普、换手、10类图表、HTML/CSV/JSON |
| 中文网页 | 参数设置、文件上传、研究记录切换、图表、表格筛选、报告预览、ZIP下载 |

八个开发阶段均已验收。网页是研究入口的轻量交互层，不提供实盘交易。

## 快速开始：使用中文网页

需要 Python 3.10 或以上版本。以下命令适用于 Windows，在项目根目录运行。

### 1. 获取源码并安装

```powershell
git clone https://github.com/sunqinxue2026/multi-factor-research.git
cd multi-factor-research
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-ui.txt
```

`requirements-ui.txt` 包含研究核心及网页依赖，无需重复安装两份依赖。

### 2. 启动网页

```powershell
.venv\Scripts\python.exe -m streamlit run scripts/research_ui.py --server.address 127.0.0.1 --server.port 8519 --browser.gatherUsageStats false
```

启动后使用终端提示的浏览器入口。保持启动终端运行；结束服务时在该终端按 `Ctrl+C`。若指定位置被其他程序占用，可将 `--server.port` 改为其他未使用的值。不要因此关闭其他项目。

### 3. 运行一次研究

1. 左侧选择“确定性合成数据”，无需上传文件。
2. 设置窗口、评价周期、分组数、Top N、调仓频率和资金。
3. 点击“运行研究”，等待完成提示。
4. 在“查看研究记录”中确认当前记录。
5. 查看顶部指标，并依次使用“研究图表”“交易与数据”“完整报告”“参数与局限”“下载结果”。

每次运行生成独立记录。默认合成数据用于验证流程，不代表真实投资结论。

**使用文档：** [网页操作说明](docs/轻量界面使用说明.md) · [系统网页使用教程 PDF](docs/系统网页使用教程.pdf)

## 网页参数与结果

| 参数 | 默认值 | 说明 |
|---|---|---|
| 因子回看窗口 | 20 | 三个因子共用的交易日窗口，范围2～252 |
| 未来收益评价周期 | 5、20 | 可多选，仅用于事后评价，不参与当时选股 |
| 因子分组数 | 5 | 支持5组或10组 |
| 选股数量 Top N | 5 | 范围1～100；有效候选不足时保留现金 |
| 调仓频率 | 每周 | 支持每周、每月 |
| 初始资金 | 100000元 | 范围1000～100000000元 |

网页使用三因子等权、既定因子方向和正式入口的成本配置，目前不能在网页编辑因子权重、方向或费率。确切参数在“参数与局限”中查看。

| 页签 | 用法 |
|---|---|
| 研究图表 | 选择IC、RankIC、相关性、分组、净值、回撤、换手或订单图 |
| 交易与数据 | 选择数据表；存在股票列时可按股票筛选；页面最多显示2000行 |
| 完整报告 | 阅读当前记录的正式HTML报告；下载请使用下载页签 |
| 参数与局限 | 核对来源、参数、环境与限制；日志可能属于最近一次运行 |
| 下载结果 | 先准备完整ZIP，再下载；也可单独下载JSON或CSV |

完整ZIP需要整体解压，保留HTML与图片的相对目录。目标权重不等于实际持仓，订单不等于成交，最终资产不等于现金。

## 使用外部行情

选择“上传外部CSV”，同时上传以下三份文件，并填写日历来源、版本。每份文件最多20MB。

### 行情 CSV

```csv
symbol,trade_date,open,high,low,close,volume,amount
000001,2025-01-02,10,12,9,11,1000,11000
```

- 股票代码保留为文本，日期使用 `YYYY-MM-DD`，股票和日期的联合键必须唯一。
- 有效价格大于0，成交量和成交额非负；OHLC关系必须合法。
- 缺失值留空，不用0冒充缺失；不自动前向填充价格。
- 单位必须为人民币元、股、人民币元，不自动换算手、千元等单位。

### 来源元数据 JSON

```json
{
  "source": "用户自备行情",
  "market": "CN",
  "price_type": "未复权",
  "data_as_of": "2025-01-06",
  "is_synthetic": false,
  "universe_description": "填写实际证券范围和筛选方式",
  "includes_delisted": null,
  "price_unit": "CNY",
  "volume_unit": "股",
  "amount_unit": "CNY"
}
```

内容必须反映实际数据；`price_type` 可为未复权、前复权或后复权。研究价格与执行价格是否适用相同口径，仍需使用者核查；当前系统没有完整公司行动账户处理，不能把复权报价直接解释为实际可成交价格。

### 交易日历 CSV

```csv
trade_date
2025-01-02
2025-01-03
2025-01-06
```

只允许 `trade_date` 一列，不重复，只列实际开放交易日。行情必须落在日历内，日历与行情不能晚于元数据截至日期。系统不会替用户认证外部日历。当前报告的 `calendar_is_exchange_verified` 固定为 `false`，不代表自动核验过交易所日历。

要获得有效研究结果，还需要足够的历史长度、横截面股票数和可计算价格；极短样本可能成功输出但没有有效评分或IC。

## 命令行使用

不使用网页时，只需安装 `requirements.txt`。

```powershell
.venv\Scripts\python.exe -I -X utf8 scripts/run_stage8.py --output reports/research_001
```

调整参数：

```powershell
.venv\Scripts\python.exe -I -X utf8 scripts/run_stage8.py --window 20 --horizons 5 20 --groups 5 --top-n 5 --frequency monthly --initial-cash 100000 --output reports/research_002
```

外部数据：

```powershell
.venv\Scripts\python.exe -I -X utf8 scripts/run_stage8.py --csv data/market.csv --metadata data/metadata.json --calendar data/calendar.csv --calendar-source user-calendar --calendar-version v1 --output reports/research_003
```

输出目录必须尚未存在。完整入口生成19张CSV、10张PNG、中文HTML报告和JSON摘要。网页调用同一个入口，不另写计算逻辑。

## 代码结构

```text
src/multi_factor_research/
  data.py             行情校验、交易日历与面板
  factors.py          三个基础因子
  preprocessing.py    横截面处理和审计
  analysis.py         标签、IC、RankIC与分组
  portfolio.py        综合评分与调仓目标
  execution.py        共享现金执行和账户快照
  performance.py      组合绩效
  visualization.py    研究图表
  report.py           一致性检查与报告导出
scripts/
  run_stage8.py       完整命令行入口
  research_ui.py      中文网页入口
  其他阶段脚本         分模块运行入口
 tests/               自动化测试
 data/test/           小型合成契约样例
 docs/                使用教程、需求、设计、阶段验收记录
```

研究评价与交易决策分离：未来收益标签仅进入IC与分组分析；综合评分只读取历史因子的预处理结果。信号在收盘后确定，计划在下一显式交易日开盘执行。

## 测试与兼容性

```powershell
.venv\Scripts\python.exe -I -X utf8 -m pytest -o pythonpath=src -p no:cacheprovider -q
```

既有研究核心全量测试记录为166项通过，覆盖手算、缺失窗口、历史不变性、目标权重、现金核算、报告一致性及重复运行。核心曾在Python 3.10与3.12环境验证；不表示所有依赖版本组合均通过。网页有当前环境的交互验证记录，尚无独立Python 3.10网页依赖矩阵验证。部分Streamlit接口存在已知弃用提示。

## 数据与结果管理

- GitHub保留源码、测试、依赖、合成契约样例和项目文档。
- `reports/`、虚拟环境、缓存、数据库、本机配置及非白名单数据由Git忽略。
- 上传数据保存在本机研究目录，不自动提交GitHub；下载包可能含原始数据，分享前检查许可。
- 阶段文档用于追溯设计与验收，不替代当前使用教程；旧记录按当时环境解释。

## 限制与适用范围

- 不提供实盘下单、多人任务队列、账号管理或公网部署配置。
- 没有完整历史成分股、退市样本、公司行动、涨跌停与成交量撮合约束，未消除幸存者偏差。
- 未接入MySQL/SQLAlchemy持久化，没有SciPy显著性检验；它们不是当前已实现功能。
- 分组和高低组收益是研究统计，不是含全部执行约束的账户收益。重叠标签下ICIR不能作为独立样本显著性结论。
- 目标换手与实际换手定义不同；缺失估值不填充，绩效沿用跳过无效估值的口径，跨缺口收益不应当作严格日收益。
- 输出不是原子写入，失败可能保留部分文件；网页单次研究等待上限为120秒。

## 项目文档

- [需求说明书](docs/需求说明书.md)
- [总体设计](docs/第一阶段_总体设计.md)
- [开发计划](docs/开发计划.md)与[开发进度](docs/开发进度.md)
- [技术决策](docs/技术决策.md)
- [阶段八验收报告](docs/第八阶段_可视化与研究报告验收.md)

其他阶段验收与学习资料保留在 `docs`，用于查看实现过程。
