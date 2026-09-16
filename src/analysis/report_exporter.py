"""分析报告导出器。

将单通道或多通道分析结果导出为多 sheet Excel 报告：
- 汇总 sheet：实验元数据 + 各通道简略统计
- 每通道分析 sheet：详细指标表 + 关键参数柱状图（openpyxl 原生）
- 对比 sheet（可选）：三态横向对比
- 数据预览 sheet：原始/标定后数据前 N 行

依赖 openpyxl。
"""

import numpy as np
from pathlib import Path
from typing import Optional, Union

from ..utils.logger import logger
from ..storage.hdf5_reader import RecordingData
from ..device.sensor_types import get_sensor_meta, SENSOR_META


# ══════════════════════════════════════════════════════════════════════
# 指标提取器：将各种 *Result 对象转为 {指标名: 值} 字典
# ══════════════════════════════════════════════════════════════════════


def _extract_ecg(r) -> dict:
    d = {
        "平均心率(bpm)": r.heart_rate,
        "心搏数": r.n_beats,
    }
    if r.sdnn is not None:
        d["SDNN(ms)"] = r.sdnn
    if r.rmssd is not None:
        d["RMSSD(ms)"] = r.rmssd
    if r.pnn50 is not None:
        d["pNN50(%)"] = r.pnn50
    if r.mean_rr is not None:
        d["平均RR(ms)"] = r.mean_rr
    if r.lf_power is not None:
        d["LF功率(ms^2)"] = r.lf_power
    if r.hf_power is not None:
        d["HF功率(ms^2)"] = r.hf_power
    if r.lf_hf_ratio is not None:
        d["LF/HF"] = r.lf_hf_ratio
    return d


def _extract_emg(r) -> dict:
    return {
        "RMS(mV)": r.rms,
        "平均频率MNF(Hz)": r.mean_freq,
        "中值频率MDF(Hz)": r.median_freq,
        "最大振幅(mV)": r.max_amplitude,
    }


def _extract_eda(r) -> dict:
    d = {
        "平均SCL(uS)": r.mean_scl,
        "SCR事件数": r.n_scr,
    }
    if len(r.scr_amplitudes) > 0:
        d["平均SCR幅度(uS)"] = float(np.mean(r.scr_amplitudes))
        d["最大SCR幅度(uS)"] = float(np.max(r.scr_amplitudes))
    return d


def _extract_eeg(r) -> dict:
    d = {}
    for band, power in r.band_powers.items():
        d[f"{band}_功率(uV^2)"] = power
    d["总功率"] = r.total_power
    if r.band_powers.get("Alpha", 0) > 0 and r.band_powers.get("Theta", 0) > 0:
        d["Alpha/Theta"] = r.band_powers["Alpha"] / r.band_powers["Theta"]
    return d


def _extract_resp(r) -> dict:
    d = {
        "呼吸频率(次/分)": r.breathing_rate,
        "平均幅度": r.mean_amplitude,
    }
    if r.ie_ratio is not None:
        d["吸呼比I/E"] = r.ie_ratio
    return d


_EXTRACTORS = {
    "ECG":  _extract_ecg,
    "EMG":  _extract_emg,
    "EDA":  _extract_eda,
    "EEG":  _extract_eeg,
    "RESP": _extract_resp,
}


def _format_value(v) -> str:
    """将数值格式化为显示字符串。"""
    if v is None:
        return "N/A"
    if isinstance(v, (int, np.integer)):
        return str(int(v))
    if isinstance(v, (float, np.floating)):
        f = float(v)
        if np.isnan(f) or np.isinf(f):
            return "N/A"
        return f"{f:.4f}"
    return str(v)


# ══════════════════════════════════════════════════════════════════════
# 主导出函数
# ══════════════════════════════════════════════════════════════════════


def export_report(
    result,
    sensor_type: str,
    sampling_rate: int,
    recording: RecordingData,
    file_path: str,
    comparison_data: Optional[list[dict]] = None,
) -> bool:
    """导出分析报告为 Excel。

    Args:
        result: 单通道分析结果对象 (ECGResult / EMGResult / ...)
        sensor_type: 传感器类型标识
        sampling_rate: 采样率
        recording: 录制数据对象
        file_path: 输出 xlsx 文件路径
        comparison_data: 可选的对比数据列表，
            [{phase, stype, result}, ...]，若提供则生成对比 sheet

    Returns:
        True 成功，False 失败
    """
    try:
        from openpyxl import Workbook
        from openpyxl.chart import BarChart, Reference
        from openpyxl.chart.label import DataLabelList
        from openpyxl.styles import Font, Alignment, PatternFill
    except ImportError:
        logger.error("openpyxl 未安装，无法导出 Excel 报告")
        return False

    try:
        wb = Workbook()
        wb.remove(wb.active)  # 移除默认 sheet

        # 样式
        header_font = Font(bold=True, color="FFFFFF")
        header_fill = PatternFill("solid", fgColor="4472C4")
        title_font = Font(bold=True, size=14)

        # ── Sheet 1: 汇总 ──
        ws_summary = wb.create_sheet("汇总")
        ws_summary["A1"] = "PsychLab V4 分析报告"
        ws_summary["A1"].font = title_font
        ws_summary["A2"] = f"生成时间: {recording.start_time}"
        ws_summary["A3"] = f"采集设备: {recording.device_address}"
        ws_summary["A4"] = f"采样率: {sampling_rate} Hz"
        ws_summary["A5"] = f"通道数: {recording.n_channels}"
        ws_summary["A6"] = f"时长: {recording.duration_sec:.1f} 秒"
        ws_summary["A7"] = f"采集阶段: {recording.phase or '未指定'}"
        ws_summary["A8"] = f"样本数: {recording.raw_data.shape[0]}"

        # 传感器列表
        ws_summary["A10"] = "传感器列表"
        ws_summary["A10"].font = Font(bold=True)
        ws_summary["A11"] = "通道"
        ws_summary["B11"] = "类型"
        ws_summary["C11"] = "名称"
        for c in ("A11", "B11", "C11"):
            ws_summary[c].font = header_font
            ws_summary[c].fill = header_fill
            ws_summary[c].alignment = Alignment(horizontal="center")

        for i, sinfo in enumerate(recording.sensor_info):
            if isinstance(sinfo, (list, tuple)) and len(sinfo) >= 3:
                port, stype, name_cn = sinfo[0], sinfo[1], sinfo[2]
            elif isinstance(sinfo, dict):
                port = sinfo.get("port", i)
                stype = sinfo.get("type", "UNKNOWN")
                name_cn = sinfo.get("name_cn", stype)
            else:
                port, stype, name_cn = i, str(sinfo), str(sinfo)
            ws_summary.cell(row=12 + i, column=1, value=f"通道{port}")
            ws_summary.cell(row=12 + i, column=2, value=stype)
            ws_summary.cell(row=12 + i, column=3, value=name_cn)

        # ── Sheet 2: 当前通道详细分析 ──
        ws_detail = wb.create_sheet(f"{sensor_type}_分析")
        ws_detail["A1"] = f"{get_sensor_meta(sensor_type).name_cn} 分析结果"
        ws_detail["A1"].font = title_font
        ws_detail["A2"] = f"采样率: {sampling_rate} Hz"
        ws_detail["A3"] = f"分析时长: {recording.duration_sec:.1f} 秒"

        # 指标表
        ws_detail["A5"] = "指标"
        ws_detail["B5"] = "值"
        for c in ("A5", "B5"):
            ws_detail[c].font = header_font
            ws_detail[c].fill = header_fill
            ws_detail[c].alignment = Alignment(horizontal="center")

        extractor = _EXTRACTORS.get(sensor_type)
        if extractor is None:
            # 未知类型，输出基本统计
            metrics = {"信号类型": sensor_type, "样本数": len(recording.raw_data)}
        else:
            metrics = extractor(result)

        for i, (name, value) in enumerate(metrics.items()):
            ws_detail.cell(row=6 + i, column=1, value=name)
            ws_detail.cell(row=6 + i, column=2, value=_format_value(value))

        # 关键参数柱状图（取前 10 项避免拥挤）
        chart_items = list(metrics.items())[:10]
        if chart_items:
            chart_start_row = 6 + len(metrics) + 2
            ws_detail.cell(row=chart_start_row, column=1, value="指标")
            ws_detail.cell(row=chart_start_row, column=2, value="值")
            for c in (1, 2):
                cell = ws_detail.cell(row=chart_start_row, column=c)
                cell.font = header_font
                cell.fill = header_fill

            for i, (name, value) in enumerate(chart_items):
                v = value if isinstance(value, (int, float)) else 0
                if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
                    v = 0
                ws_detail.cell(row=chart_start_row + 1 + i, column=1, value=name)
                ws_detail.cell(row=chart_start_row + 1 + i, column=2, value=float(v))

            chart = BarChart()
            chart.type = "col"
            chart.style = 10
            chart.title = f"{sensor_type} 关键指标"
            chart.y_axis.title = "数值"
            chart.x_axis.title = "指标"

            data = Reference(
                ws_detail,
                min_col=2, min_row=chart_start_row,
                max_row=chart_start_row + len(chart_items),
            )
            cats = Reference(
                ws_detail,
                min_col=1, min_row=chart_start_row + 1,
                max_row=chart_start_row + len(chart_items),
            )
            chart.add_data(data, titles_from_data=True)
            chart.set_categories(cats)
            chart.dataLabels = DataLabelList(showVal=True)
            chart.height = 10
            chart.width = 20
            ws_detail.add_chart(chart, "D5")

        # ── Sheet 3: 数据预览 ──
        ws_preview = wb.create_sheet("数据预览")
        ws_preview["A1"] = "数据预览（前 1000 行）"
        ws_preview["A1"].font = title_font

        ws_preview.cell(row=3, column=1, value="时间(秒)")
        for c in range(recording.n_channels):
            try:
                sinfo = recording.sensor_info[c]
                if isinstance(sinfo, (list, tuple)) and len(sinfo) >= 2:
                    stype = sinfo[1]
                else:
                    stype = "UNKNOWN"
            except (IndexError, TypeError):
                stype = "UNKNOWN"
            ws_preview.cell(row=3, column=2 + c,
                              value=f"通道{c+1}_{get_sensor_meta(stype).name_cn}")

        preview_n = min(1000, len(recording.raw_data))
        for i in range(preview_n):
            t = float(recording.timestamps[i]) if i < len(recording.timestamps) else i / sampling_rate
            ws_preview.cell(row=4 + i, column=1, value=t)
            for c in range(recording.n_channels):
                v = float(recording.raw_data[i, c])
                ws_preview.cell(row=4 + i, column=2 + c, value=v)

        # ── Sheet 4: 对比（可选）──
        if comparison_data:
            ws_cmp = wb.create_sheet("三态对比")
            ws_cmp["A1"] = "三态分段对比"
            ws_cmp["A1"].font = title_font

            # 用第一个文件的指标作为行
            first = comparison_data[0]
            cmp_stype = first["stype"]
            cmp_extractor = _EXTRACTORS.get(cmp_stype)
            if cmp_extractor:
                metric_names = list(cmp_extractor(first["result"]).keys())
                phases = [d["phase"] for d in comparison_data]

                # 表头
                ws_cmp.cell(row=3, column=1, value="指标")
                for c, ph in enumerate(phases):
                    ws_cmp.cell(row=3, column=2 + c, value=ph)
                for c in range(1, 2 + len(phases)):
                    cell = ws_cmp.cell(row=3, column=c)
                    cell.font = header_font
                    cell.fill = header_fill
                    cell.alignment = Alignment(horizontal="center")

                # 数据行
                for r, mname in enumerate(metric_names):
                    ws_cmp.cell(row=4 + r, column=1, value=mname)
                    for c, rec in enumerate(comparison_data):
                        vals = cmp_extractor(rec["result"])
                        v = vals.get(mname)
                        ws_cmp.cell(row=4 + r, column=2 + c,
                                      value=_format_value(v))

                # 对比柱状图（第一个指标）
                if metric_names and len(comparison_data) > 1:
                    chart = BarChart()
                    chart.type = "col"
                    chart.style = 12
                    chart.title = f"{metric_names[0]} - 三态对比"
                    chart.y_axis.title = "数值"
                    chart.x_axis.title = "阶段"
                    data = Reference(
                        ws_cmp, min_col=2, min_row=3,
                        max_col=1 + len(phases), max_row=4,
                    )
                    cats = Reference(
                        ws_cmp, min_col=1, min_row=4, max_row=4,
                    )
                    chart.add_data(data, titles_from_data=True, from_rows=True)
                    chart.set_categories(cats)
                    chart.dataLabels = DataLabelList(showVal=True)
                    chart.height = 10
                    chart.width = 18
                    ws_cmp.add_chart(chart, f"{chr(ord('A') + 2 + len(phases))}3")

        # ── 保存 ──
        out_path = Path(file_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        wb.save(str(out_path))
        logger.info(f"分析报告已导出: {out_path}")
        return True

    except Exception as e:
        logger.error(f"导出 Excel 报告失败: {e}", exc_info=True)
        return False


def export_comparison_report(
    comparison_data: list[dict],
    recording: RecordingData,
    sampling_rate: int,
    file_path: str,
) -> bool:
    """导出三态对比报告。

    Args:
        comparison_data: [{phase, stype, result}, ...]
        recording: 主录制数据（用于元数据）
        sampling_rate: 采样率
        file_path: 输出 xlsx 路径

    Returns:
        True 成功，False 失败
    """
    if not comparison_data:
        return False
    first_stype = comparison_data[0]["stype"]
    # 用第一个对比项的 result 占位（实际对比信息在 comparison_data 中）
    placeholder_result = comparison_data[0]["result"]
    return export_report(
        result=placeholder_result,
        sensor_type=first_stype,
        sampling_rate=sampling_rate,
        recording=recording,
        file_path=file_path,
        comparison_data=comparison_data,
    )
