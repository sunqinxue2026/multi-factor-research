"""中文轻量研究界面；仅编排已有研究入口，不复制计算逻辑。"""
from __future__ import annotations

from datetime import datetime
from io import BytesIO
import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4
import zipfile

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / 'reports'
CHARTS = {
    'ic_series': ('IC时间序列', '定向因子与未来收益的线性相关性；零线以上更符合预设方向。'),
    'rank_ic_series': ('RankIC时间序列', '因子排名与未来收益排名的相关性，不是胜率。'),
    'ic_distribution': ('IC分布', '评价日期的IC分布；多日标签重叠，不假设样本独立。'),
    'factor_correlation': ('因子相关性', '原始因子每日横截面相关系数的时间均值。'),
    'group_returns': ('分组累计收益', '固定锚点非重叠区间统计，不是可执行账户净值。'),
    'long_short': ('高低组收益差', '假设性收益差，未计融券、保证金与交易成本。'),
    'portfolio_nav': ('组合净值', '来自共享现金执行后的账户估值，初始资金归一为1。'),
    'drawdown': ('组合回撤', '相对历史峰值的跌幅，包含初始资金。'),
    'turnover': ('目标与实际换手', '目标为含现金半L1距离；实际为双边成交金额/调仓前资产，不可直接等同。'),
    'orders': ('订单状态', '按执行日统计订单状态，不是盈利交易数量。'),
}
TABLES = {
    'ic_summary': 'IC汇总', 'daily_ic': '每日IC', 'group_summary': '分组汇总',
    'scores': '股票评分', 'target_weights': '目标权重', 'target_changes': '目标变化',
    'rebalances': '调仓计划', 'orders': '订单', 'trades': '成交',
    'snapshots': '账户快照', 'positions': '最终持仓', 'equity_curve': '净值明细',
    'forward_returns': '未来收益标签', 'market': '行情面板',
}


def run_research(options: dict, uploads: dict[str, bytes] | None = None,
                 calendar_source: str = '', calendar_version: str = '') -> tuple[Path, str]:
    """使用独立进程运行正式入口，限制单次等待，不使用shell。"""
    token = datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid4().hex[:8]
    output = REPORTS / ('ui_' + token)
    command = [sys.executable, '-I', '-X', 'utf8', str(ROOT / 'scripts/run_stage8.py'),
               '--output', str(output), '--window', str(options['window']),
               '--horizons', *map(str, options['horizons']), '--groups', str(options['groups']),
               '--top-n', str(options['top_n']), '--frequency', options['frequency'],
               '--initial-cash', str(options['initial_cash'])]
    if uploads:
        # 输入文件在忽略的reports中留存，便于追溯；不使用上传文件原名。
        folder = REPORTS / ('ui_input_' + token)
        folder.mkdir(parents=True, exist_ok=False)
        for key, content in uploads.items():
            (folder / key).write_bytes(content)
        command.extend(['--csv', str(folder / 'market.csv'), '--metadata', str(folder / 'metadata.json'),
                        '--calendar', str(folder / 'calendar.csv'), '--calendar-source', calendar_source,
                        '--calendar-version', calendar_version])
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                               encoding='utf-8', errors='replace', timeout=120)
    log = completed.stdout + '\n' + completed.stderr
    if completed.returncode != 0:
        raise RuntimeError(log[-16000:] or '研究入口未成功结束')
    return output, log


def report_zip(folder: Path) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(folder.rglob('*')):
            if path.is_file():
                archive.write(path, path.relative_to(folder))
    return buffer.getvalue()


def main() -> None:
    st.set_page_config(page_title='多因子研究工作台', page_icon='📊', layout='wide')
    st.title('多因子研究工作台')
    st.caption('Python 多因子选股与组合研究系统 · 轻量展示界面')
    st.info('合成数据用于验证工程链路，不证明因子有效或策略盈利。研究评价与选股决策保持分离。')
    with st.sidebar:
        st.header('新建研究')
        mode = st.radio('数据来源', ['确定性合成数据', '上传外部CSV'])
        uploads = None
        source = version = ''
        if mode == '上传外部CSV':
            st.caption('八列行情、来源JSON、显式交易日历必须同时提供；最大每份20MB。')
            market = st.file_uploader('行情CSV', type=['csv'], key='market_upload')
            metadata = st.file_uploader('来源元数据JSON', type=['json'], key='metadata_upload')
            calendar = st.file_uploader('交易日历CSV', type=['csv'], key='calendar_upload')
            source = st.text_input('日历来源')
            version = st.text_input('日历版本', 'v1')
            if all(x is not None for x in (market, metadata, calendar)):
                uploads = {'market.csv': market.getvalue(), 'metadata.json': metadata.getvalue(),
                           'calendar.csv': calendar.getvalue()}
        with st.form('research_parameters'):
            window = st.number_input('因子回看窗口（交易日）', 2, 252, 20)
            horizons = st.multiselect('未来收益评价周期', [1, 5, 10, 20, 60], [5, 20])
            groups = st.selectbox('因子分组数', [5, 10])
            top_n = st.number_input('选股数量 Top N', 1, 100, 5)
            frequency = st.selectbox('调仓频率', ['weekly', 'monthly'], format_func=lambda x: '每周' if x == 'weekly' else '每月')
            initial = st.number_input('初始资金（元）', 1000, 100000000, 100000, step=1000)
            submitted = st.form_submit_button('运行研究', type='primary', use_container_width=True)
        st.caption('默认三因子等权，1%/99%截尾、横截面Z-score；手续费和滑点沿用正式执行入口。')
    if submitted:
        error = None
        if not horizons:
            error = '请至少选择一个未来收益评价周期。'
        elif mode == '上传外部CSV' and (not uploads or not source.strip() or not version.strip()):
            error = '请完整上传三份数据文件并填写日历来源、版本。'
        elif uploads and any(len(x) > 20 * 1024 * 1024 for x in uploads.values()):
            error = '单份上传文件不能超过20MB。'
        if error:
            st.error(error)
        else:
            try:
                with st.spinner('正在计算因子、运行组合并生成报告，请稍候…'):
                    folder, log = run_research(dict(window=window, horizons=horizons, groups=groups,
                        top_n=top_n, frequency=frequency, initial_cash=initial), uploads, source.strip(), version.strip())
                st.session_state['active_report'] = str(folder)
                st.session_state['run_log'] = log
                st.success('研究完成，结果已保留为独立运行记录。')
            except (RuntimeError, subprocess.TimeoutExpired, OSError) as exc:
                st.error('本次研究未完成。失败目录可能保留部分文件；重新运行将使用新目录。')
                with st.expander('运行错误', expanded=True):
                    st.code(str(exc))
    records = sorted((p.parent for p in REPORTS.glob('*/研究报告.html')
                      if (p.parent / 'summary.json').is_file()), key=lambda p: p.name, reverse=True)
    if not records:
        st.subheader('开始你的第一次研究')
        st.write('左侧保持默认参数，点击“运行研究”，即可得到因子分析、组合净值、交易明细和完整报告。')
        return
    active = Path(st.session_state.get('active_report', str(records[0])))
    if active not in records:
        active = records[0]
    selected = st.selectbox('查看研究记录', records, index=records.index(active), format_func=lambda p: p.name)
    st.session_state['active_report'] = str(selected)
    try:
        summary = json.loads((selected / 'summary.json').read_text(encoding='utf-8'))
    except (ValueError, OSError) as exc:
        st.error(f'运行摘要无法读取：{exc}')
        return
    metrics = summary['metrics']
    columns = st.columns(4)
    for col, label, key, percent in zip(columns, ['累计收益', '最大回撤', '最终资产', '成交笔数'],
            ['total_return', 'max_drawdown', 'final_equity', 'trade_count'], [True, True, False, False]):
        value = metrics.get(key)
        col.metric(label, '不可计算' if value is None else f'{value:.2%}' if percent else f'{value:,.2f}' if key == 'final_equity' else str(value))
    if summary.get('metadata', {}).get('is_synthetic'):
        st.warning('当前记录为合成数据演示；不应用这些收益评价真实投资价值。')
    tabs = st.tabs(['研究图表', '交易与数据', '完整报告', '参数与局限', '下载结果'])
    with tabs[0]:
        chart = st.selectbox('选择图表', list(CHARTS), format_func=lambda x: CHARTS[x][0])
        st.caption(CHARTS[chart][1])
        image = selected / 'charts' / (chart + '.png')
        if image.is_file():
            st.image(str(image), use_container_width=True)
        else:
            st.info('该记录没有此图表。')
    with tabs[1]:
        name = st.selectbox('数据表', list(TABLES), format_func=lambda x: TABLES[x])
        path = selected / (name + '.csv')
        if path.is_file():
            try:
                table = pd.read_csv(path, dtype={'symbol': 'string'})
                if 'symbol' in table:
                    symbol = st.selectbox('筛选股票', ['全部'] + sorted(table.symbol.dropna().unique().tolist()))
                    if symbol != '全部':
                        table = table[table.symbol.eq(symbol)]
                st.caption(f'筛选后共{len(table)}行，页面最多显示前2000行；完整数据可下载。')
                st.dataframe(table.head(2000), use_container_width=True, hide_index=True)
            except pd.errors.EmptyDataError:
                st.info('本次没有此类记录。')
    with tabs[2]:
        # 使用本次正式报告HTML；图像转data URL以支持iframe内完整显示。
        import base64
        html = (selected / '研究报告.html').read_text(encoding='utf-8')
        for image in (selected / 'charts').glob('*.png'):
            relative = image.relative_to(selected).as_posix()
            encoded = base64.b64encode(image.read_bytes()).decode('ascii')
            html = html.replace(f'src="{relative}"', f'src="data:image/png;base64,{encoded}"')
        st.caption('下方报告为正式报告预览；文件索引下载请使用“下载结果”。')
        components.html(html, height=950, scrolling=True)
    with tabs[3]:
        st.json({k: summary.get(k) for k in ['metadata', 'parameters', 'run', 'calendar']})
        for limitation in summary.get('limitations', []):
            st.write('• ' + limitation)
        if 'run_log' in st.session_state:
            with st.expander('最近一次运行日志（可能不是当前选中的记录）'):
                st.code(st.session_state['run_log'])
    with tabs[4]:
        st.caption('整包包含HTML及相对引用的图片，解压后可完整查看。真实数据下载包请勿提交公开仓库。')
        if st.button('准备完整下载包'):
            st.session_state['download_bundle'] = (str(selected), report_zip(selected))
        bundle = st.session_state.get('download_bundle')
        if bundle and bundle[0] == str(selected):
            st.download_button('下载完整研究结果 ZIP', bundle[1], file_name=selected.name + '.zip', mime='application/zip')
        st.download_button('下载运行摘要', (selected / 'summary.json').read_bytes(), 'summary.json', 'application/json')
        csv_files = sorted(selected.glob('*.csv'))
        if csv_files:
            csv_path = st.selectbox('选择CSV下载', csv_files, format_func=lambda p: p.name)
            st.download_button('下载所选CSV', csv_path.read_bytes(), csv_path.name, 'text/csv')


if __name__ == '__main__':
    main()
