from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

STATUS_TABLE_COLUMNS = [
    "数据源",
    "数据类型",
    "调取方式",
    "状态",
    "状态说明",
    "开始时间",
    "结束时间",
    "用时",
    "原始数据量",
    "原始病原体数量（去重后）",
    "未匹配病原体数量（去重后）",
    "成功匹配行数",
    "未匹配行数",
    "总行数（处理后）",
]

TIME_FORMAT = "%Y/%m/%d %H:%M:%S"
STRUCTURED_SUFFIXES = {".csv", ".tsv", ".xlsx", ".xls", ".parquet"}
SEMI_STRUCTURED_SUFFIXES = {".json", ".xml", ".geojson"}


@dataclass
class MatchStatusMetadata:
    data_source: str
    data_type: str
    fetch_method: str
    original_row_count: int | None
    original_unique_pathogen_count: int | None


def load_match_status_metadata(input_path: Path) -> MatchStatusMetadata:
    dataframe = _read_input_dataframe(input_path)
    return MatchStatusMetadata(
        data_source=_infer_data_source(input_path, dataframe),
        data_type=_infer_data_type(input_path, dataframe),
        fetch_method=_infer_fetch_method(input_path, dataframe),
        original_row_count=int(len(dataframe)),
        original_unique_pathogen_count=_count_unique_pathogens(dataframe),
    )


def build_fallback_metadata(input_path: Path) -> MatchStatusMetadata:
    return MatchStatusMetadata(
        data_source=input_path.stem,
        data_type=_infer_data_type(input_path, None),
        fetch_method=_infer_fetch_method(input_path, None),
        original_row_count=None,
        original_unique_pathogen_count=None,
    )


class MatchStatusTable:
    def __init__(self, table_path: Path, metadata: MatchStatusMetadata) -> None:
        self.table_path = table_path
        self.metadata = metadata
        self.start_time = datetime.now()
        self._rows = self._load_existing_rows()
        self._start_row_index: int | None = None

    def mark_started(self) -> None:
        self._rows.loc[len(self._rows)] = self._build_row(
            status="病原体匹配开始",
            status_description="程序启动，开始进行病原体匹配",
            end_time=None,
            duration_text="",
            summary=None,
        )
        self._start_row_index = len(self._rows) - 1
        self._save_rows()

    def mark_finished(self, summary: dict[str, Any]) -> None:
        end_time = datetime.now()
        duration_text = _format_duration(self.start_time, end_time)
        final_status, final_description = _build_final_status(summary)

        if self._start_row_index is not None and self._start_row_index < len(self._rows):
            self._rows.loc[self._start_row_index] = self._build_row(
                status="病原体匹配开始",
                status_description="程序启动，开始进行病原体匹配",
                end_time=end_time,
                duration_text=duration_text,
                summary=summary,
            )

        self._rows.loc[len(self._rows)] = self._build_row(
            status=final_status,
            status_description=final_description,
            end_time=end_time,
            duration_text=duration_text,
            summary=summary,
        )
        self._save_rows()

    def mark_failed(self, exc: Exception) -> None:
        end_time = datetime.now()
        duration_text = _format_duration(self.start_time, end_time)

        if self._start_row_index is not None and self._start_row_index < len(self._rows):
            self._rows.loc[self._start_row_index] = self._build_row(
                status="病原体匹配开始",
                status_description="程序启动，开始进行病原体匹配",
                end_time=end_time,
                duration_text=duration_text,
                summary=None,
            )

        self._rows.loc[len(self._rows)] = self._build_row(
            status="病原体匹配失败",
            status_description=_short_error_message(exc),
            end_time=end_time,
            duration_text=duration_text,
            summary=None,
        )
        self._save_rows()

    def _build_row(
        self,
        status: str,
        status_description: str,
        end_time: datetime | None,
        duration_text: str,
        summary: dict[str, Any] | None,
    ) -> dict[str, Any]:
        summary = summary or {}
        return {
            "数据源": self.metadata.data_source,
            "数据类型": self.metadata.data_type,
            "调取方式": self.metadata.fetch_method,
            "状态": status,
            "状态说明": status_description,
            "开始时间": self.start_time.strftime(TIME_FORMAT),
            "结束时间": end_time.strftime(TIME_FORMAT) if end_time else "",
            "用时": duration_text,
            "原始数据量": _coalesce_metric(summary.get("total_rows"), self.metadata.original_row_count),
            "原始病原体数量（去重后）": _coalesce_metric(
                summary.get("unique_original_pathogens"),
                self.metadata.original_unique_pathogen_count,
            ),
            "未匹配病原体数量（去重后）": _coalesce_metric(summary.get("unique_unmatched_values"), ""),
            "成功匹配行数": _coalesce_metric(summary.get("matched_rows"), ""),
            "未匹配行数": _coalesce_metric(summary.get("unmatched_rows"), ""),
            "总行数（处理后）": _coalesce_metric(summary.get("total_rows"), self.metadata.original_row_count),
        }

    def _load_existing_rows(self) -> pd.DataFrame:
        if not self.table_path.exists():
            return pd.DataFrame(columns=STATUS_TABLE_COLUMNS)

        if self.table_path.suffix.lower() == ".csv":
            dataframe = pd.read_csv(self.table_path)
        else:
            dataframe = pd.read_excel(self.table_path)

        for column in STATUS_TABLE_COLUMNS:
            if column not in dataframe.columns:
                dataframe[column] = ""
        return dataframe[STATUS_TABLE_COLUMNS].copy()

    def _save_rows(self) -> None:
        self.table_path.parent.mkdir(parents=True, exist_ok=True)
        output = self._rows.astype(object).where(pd.notna(self._rows), "")
        if self.table_path.suffix.lower() == ".csv":
            output.to_csv(self.table_path, index=False, encoding="utf-8-sig")
        else:
            output.to_excel(self.table_path, index=False)


def _read_input_dataframe(input_path: Path) -> pd.DataFrame:
    suffix = input_path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(input_path)
    if suffix == ".csv":
        return pd.read_csv(input_path)
    if suffix in SEMI_STRUCTURED_SUFFIXES:
        return pd.read_json(input_path)
    raise ValueError(f"Unsupported input file format: {input_path.suffix}")


def _infer_data_source(input_path: Path, dataframe: pd.DataFrame | None) -> str:
    if dataframe is None or "data_source" not in dataframe.columns:
        return input_path.stem

    values = [
        _clean_text(value)
        for value in dataframe["data_source"].dropna().astype(str).tolist()
        if _clean_text(value)
    ]
    unique_values = list(dict.fromkeys(values))
    if not unique_values:
        return input_path.stem
    if len(unique_values) == 1:
        return unique_values[0]
    if len(unique_values) <= 3:
        return "、".join(unique_values)
    return f"多个数据源({len(unique_values)})"


def _infer_data_type(input_path: Path, dataframe: pd.DataFrame | None) -> str:
    if dataframe is not None and "original text" in dataframe.columns:
        text_series = dataframe["original text"].dropna().astype(str).str.strip()
        if text_series.ne("").any():
            return "非结构化"

    suffix = input_path.suffix.lower()
    if suffix in SEMI_STRUCTURED_SUFFIXES:
        return "半结构化"
    if suffix in STRUCTURED_SUFFIXES:
        return "结构化"
    return "非结构化"


def _infer_fetch_method(input_path: Path, dataframe: pd.DataFrame | None) -> str:
    hints = [str(input_path).lower()]
    if dataframe is not None and "source_url" in dataframe.columns:
        hints.extend(dataframe["source_url"].dropna().astype(str).str.lower().head(20).tolist())

    if "api" in " ".join(hints):
        return "API"
    return "爬取"


def _count_unique_pathogens(dataframe: pd.DataFrame) -> int | None:
    if "pathogen_old" not in dataframe.columns:
        return None

    values = {
        _clean_text(value)
        for value in dataframe["pathogen_old"].dropna().astype(str).tolist()
        if _clean_text(value)
    }
    return int(len(values))


def _build_final_status(summary: dict[str, Any]) -> tuple[str, str]:
    matched_rows = int(summary.get("matched_rows") or 0)
    unmatched_rows = int(summary.get("unmatched_rows") or 0)
    unique_unmatched_values = int(summary.get("unique_unmatched_values") or 0)

    if unmatched_rows == 0:
        return "病原体匹配成功", "病原体匹配完成"
    if matched_rows > 0:
        return (
            "病原体匹配部分成功",
            f"{unique_unmatched_values}个未匹配病原体（去重后），{unmatched_rows}行未匹配",
        )
    return (
        "病原体匹配失败",
        f"全部{unmatched_rows}行未匹配，涉及{unique_unmatched_values}个病原体",
    )


def _coalesce_metric(primary: Any, fallback: Any) -> Any:
    return fallback if primary is None else primary


def _clean_text(value: Any) -> str:
    return " ".join(str(value).strip().split())


def _format_duration(start_time: datetime, end_time: datetime) -> str:
    total_seconds = max(int((end_time - start_time).total_seconds()), 0)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    parts: list[str] = []
    if hours:
        parts.append(f"{hours}小时")
    if minutes:
        parts.append(f"{minutes}分钟")
    if seconds or not parts:
        parts.append(f"{seconds}秒")
    return "".join(parts)


def _short_error_message(exc: Exception) -> str:
    text = _clean_text(exc)
    if not text:
        return "程序执行失败，详见日志"
    if len(text) > 120:
        return f"{text[:117]}..."
    return text
