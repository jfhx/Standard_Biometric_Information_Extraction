from __future__ import annotations

import json
import logging
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import pandas as pd

from .config import (
    CANDIDATE_LIMIT,
    REQUIRED_DICT_COLUMNS,
    REQUIRED_INPUT_COLUMNS,
    RESULT_COLUMNS,
)
from .llm_client import LLMClient
from .prompts import build_match_messages


@dataclass
class MatchDecision:
    matched: bool
    pathogen_name: str | None
    pathogen_alias: str | None
    pathogen: str | None
    pathogen_rank_1: str | None
    pathogen_rank_2: str | None
    reason: str
    source: str


class PathogenMatcher:
    def __init__(
        self,
        llm_client: LLMClient,
        cache_path: Path,
        candidate_limit: int = CANDIDATE_LIMIT,
    ) -> None:
        self.llm_client = llm_client
        self.cache_path = cache_path
        self.candidate_limit = candidate_limit
        self.logger = logging.getLogger(self.__class__.__name__)
        self._cache = self._load_cache()
        self._records: list[dict[str, Any]] = []
        self._records_by_name: dict[str, dict[str, Any]] = {}
        self._exact_name_index: dict[str, list[int]] = {}
        self._exact_alias_index: dict[str, list[int]] = {}
        self._exact_pathogen_index: dict[str, list[int]] = {}

    def run(
        self,
        input_path: Path,
        dict_path: Path,
        output_path: Path,
        unmatched_path: Path,
    ) -> dict[str, Any]:
        input_df = pd.read_excel(input_path)
        self._validate_columns(input_df, REQUIRED_INPUT_COLUMNS, str(input_path))

        dict_df = pd.read_excel(dict_path)
        self._validate_columns(dict_df, REQUIRED_DICT_COLUMNS, str(dict_path))
        self._prepare_dictionary(dict_df)

        unique_values = [
            value
            for value in input_df["pathogen_old"].dropna().astype(str).unique().tolist()
        ]
        decisions = {
            value: self.match_single(value)
            for value in unique_values
        }

        output_df = self._build_output_dataframe(input_df, decisions)
        unmatched_df = self._build_unmatched_dataframe(output_df)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        unmatched_path.parent.mkdir(parents=True, exist_ok=True)
        output_df.to_excel(output_path, index=False)
        unmatched_df.to_excel(unmatched_path, index=False)
        self._save_cache()

        matched_count = int(output_df["pathogen_name"].notna().sum())
        unmatched_count = int(output_df["pathogen_name"].isna().sum())
        self.logger.info(
            "处理完成：matched_rows=%s unmatched_rows=%s output=%s unmatched=%s",
            matched_count,
            unmatched_count,
            output_path,
            unmatched_path,
        )
        return {
            "total_rows": int(len(output_df)),
            "unique_original_pathogens": int(len(unique_values)),
            "matched_rows": matched_count,
            "unmatched_rows": unmatched_count,
            "unique_unmatched_values": int(len(unmatched_df)),
            "output_path": str(output_path),
            "unmatched_path": str(unmatched_path),
        }

    def match_single(self, pathogen_old: str) -> MatchDecision:
        raw_value = self._clean_text(pathogen_old)
        normalized = self._normalize_text(raw_value)
        if not normalized:
            return MatchDecision(
                False,
                None,
                None,
                None,
                None,
                None,
                "empty_input",
                "empty",
            )

        cached = self._cache.get(normalized)
        if isinstance(cached, dict):
            return self._decision_from_dict(cached)

        exact_name_candidates = self._exact_name_index.get(normalized, [])
        if len(exact_name_candidates) == 1:
            decision = self._record_to_decision(
                self._records[exact_name_candidates[0]],
                reason="exact_pathogen_name_match",
                source="exact_pathogen_name",
            )
            self._cache[normalized] = self._decision_to_dict(decision)
            return decision

        exact_alias_candidates = self._exact_alias_index.get(normalized, [])
        if len(exact_alias_candidates) == 1 and not exact_name_candidates:
            decision = self._record_to_decision(
                self._records[exact_alias_candidates[0]],
                reason="exact_pathogen_alias_match",
                source="exact_pathogen_alias",
            )
            self._cache[normalized] = self._decision_to_dict(decision)
            return decision

        exact_pathogen_candidates = self._exact_pathogen_index.get(normalized, [])
        if (
            len(exact_pathogen_candidates) == 1
            and not exact_name_candidates
            and not exact_alias_candidates
        ):
            decision = self._record_to_decision(
                self._records[exact_pathogen_candidates[0]],
                reason="exact_pathogen_code_match",
                source="exact_pathogen",
            )
            self._cache[normalized] = self._decision_to_dict(decision)
            return decision

        candidate_indices = self._collect_candidate_indices(normalized)
        exact_candidates = self._merge_indices(exact_name_candidates, exact_alias_candidates)
        exact_candidates = self._merge_indices(exact_candidates, exact_pathogen_candidates)
        if exact_candidates:
            candidate_indices = self._merge_indices(exact_candidates, candidate_indices)
        if not candidate_indices:
            decision = MatchDecision(
                False,
                None,
                None,
                None,
                None,
                None,
                "no_candidate_found",
                "heuristic",
            )
            self._cache[normalized] = self._decision_to_dict(decision)
            return decision

        candidate_records = [
            self._to_prompt_candidate(position, record_index)
            for position, record_index in enumerate(candidate_indices)
        ]
        decision = self._match_with_llm(
            raw_value,
            candidate_indices,
            candidate_records,
        )
        self._cache[normalized] = self._decision_to_dict(decision)
        return decision

    def _match_with_llm(
        self,
        pathogen_old: str,
        candidate_indices: list[int],
        candidate_records: list[dict[str, Any]],
    ) -> MatchDecision:
        messages = build_match_messages(pathogen_old, candidate_records)
        try:
            response = self.llm_client.chat_completion(messages)
            payload = self._extract_json_object(response.content)
        except Exception as exc:
            self.logger.error(
                "模型匹配失败：pathogen_old=%s error=%s",
                pathogen_old,
                exc,
            )
            return MatchDecision(
                False,
                None,
                None,
                None,
                None,
                None,
                str(exc),
                "llm_error",
            )

        matched = bool(payload.get("matched"))
        confidence = str(payload.get("confidence") or "").strip().lower()
        reason = self._clean_text(str(payload.get("reason") or "llm_no_reason"))
        matched_index = payload.get("matched_index")

        if not matched:
            return MatchDecision(False, None, None, None, None, None, reason, "llm")

        if confidence not in {"high", "medium"}:
            return MatchDecision(
                False,
                None,
                None,
                None,
                None,
                None,
                reason,
                "llm_low_confidence",
            )

        if not isinstance(matched_index, int):
            return MatchDecision(
                False,
                None,
                None,
                None,
                None,
                None,
                reason,
                "llm_invalid_index",
            )

        if matched_index < 0 or matched_index >= len(candidate_indices):
            return MatchDecision(
                False,
                None,
                None,
                None,
                None,
                None,
                reason,
                "llm_invalid_index",
            )

        record = self._records[candidate_indices[matched_index]]
        expected_name = record["pathogen_name"]
        returned_name = self._clean_text(str(payload.get("matched_pathogen_name") or ""))
        if returned_name and returned_name != expected_name:
            return MatchDecision(
                False,
                None,
                None,
                None,
                None,
                None,
                reason,
                "llm_name_conflict",
            )

        return self._record_to_decision(record, reason=reason, source="llm")

    def _prepare_dictionary(self, dict_df: pd.DataFrame) -> None:
        working = dict_df.copy()
        for column in working.columns:
            working[column] = working[column].map(self._clean_optional_text)
        working = working[working["pathogen_name"].notna()].copy()
        before_count = len(working)
        working = working.drop_duplicates(subset=["pathogen_name"], keep="first")
        dropped = before_count - len(working)
        if dropped:
            self.logger.info("字典中按 pathogen_name 去重，移除了 %s 行重复记录", dropped)

        records: list[dict[str, Any]] = []
        exact_name_index: defaultdict[str, list[int]] = defaultdict(list)
        exact_alias_index: defaultdict[str, list[int]] = defaultdict(list)
        exact_pathogen_index: defaultdict[str, list[int]] = defaultdict(list)
        for _, row in working.iterrows():
            pathogen_name = row["pathogen_name"]
            pathogen = row.get("pathogen")
            alias = row.get("pathogen_alias")
            normalized_name = self._normalize_text(pathogen_name)
            normalized_pathogen = self._normalize_text(pathogen)
            alias_terms = self._split_aliases(alias)
            record = {
                "pathogen_name": pathogen_name,
                "pathogen": pathogen,
                "pathogen_rank_1": row.get("pathogen_rank_1"),
                "pathogen_rank_2": row.get("pathogen_rank_2"),
                "pathogen_alias": alias,
                "_normalized_pathogen_name": normalized_name,
                "_normalized_pathogen": normalized_pathogen,
                "_normalized_aliases": alias_terms,
            }
            search_terms = self._build_search_terms(record)
            record["_search_terms"] = search_terms
            records.append(record)
            record_index = len(records) - 1
            if normalized_name:
                exact_name_index[normalized_name].append(record_index)
            if normalized_pathogen:
                exact_pathogen_index[normalized_pathogen].append(record_index)
            for term in alias_terms:
                exact_alias_index[term].append(record_index)

        self._records = records
        self._records_by_name = {
            record["pathogen_name"]: record
            for record in records
            if record.get("pathogen_name")
        }
        self._exact_name_index = dict(exact_name_index)
        self._exact_alias_index = dict(exact_alias_index)
        self._exact_pathogen_index = dict(exact_pathogen_index)
        self.logger.info("已加载病原体字典：records=%s", len(self._records))

    def _build_search_terms(self, record: dict[str, Any]) -> set[str]:
        values = {
            record.get("_normalized_pathogen_name"),
            record.get("_normalized_pathogen"),
        }
        for alias in record.get("_normalized_aliases", []):
            values.add(alias)
        return {value for value in values if value}

    def _collect_candidate_indices(self, normalized: str) -> list[int]:
        scored: list[tuple[float, int]] = []
        query_tokens = set(normalized.split())
        for index, record in enumerate(self._records):
            score = self._score_record(normalized, query_tokens, record)
            if score >= 0.35:
                scored.append((score, index))

        scored.sort(
            key=lambda item: (
                -item[0],
                self._records[item[1]]["pathogen_name"],
            )
        )
        return [index for _, index in scored[: self.candidate_limit]]

    def _score_record(
        self,
        normalized: str,
        query_tokens: set[str],
        record: dict[str, Any],
    ) -> float:
        best_score = 0.0
        for term in record["_search_terms"]:
            ratio = SequenceMatcher(None, normalized, term).ratio()
            term_tokens = set(term.split())
            if query_tokens and term_tokens:
                token_overlap = len(
                    query_tokens & term_tokens
                ) / len(query_tokens | term_tokens)
            else:
                token_overlap = 0.0
            containment = 1.0 if normalized in term or term in normalized else 0.0
            score = max(ratio, token_overlap * 0.9, containment * 0.85)
            if score > best_score:
                best_score = score
        return best_score

    def _build_output_dataframe(
        self,
        input_df: pd.DataFrame,
        decisions: dict[str, MatchDecision],
    ) -> pd.DataFrame:
        output_df = input_df.copy()
        for column in RESULT_COLUMNS:
            if column in output_df.columns:
                output_df = output_df.drop(columns=[column])

        pathogen_values = output_df["pathogen_old"].tolist()
        column_data: dict[str, list[Any]] = {column: [] for column in RESULT_COLUMNS}
        for value in pathogen_values:
            if pd.isna(value):
                decision = MatchDecision(
                    False,
                    None,
                    None,
                    None,
                    None,
                    None,
                    "empty_input",
                    "empty",
                )
            else:
                decision = decisions.get(str(value)) or self.match_single(str(value))
            column_data["pathogen_name"].append(decision.pathogen_name)
            column_data["pathogen_alias"].append(decision.pathogen_alias)
            column_data["pathogen"].append(decision.pathogen)
            column_data["pathogen_rank_1"].append(decision.pathogen_rank_1)
            column_data["pathogen_rank_2"].append(decision.pathogen_rank_2)

        insert_position = output_df.columns.get_loc("pathogen_old") + 1
        for offset, column in enumerate(RESULT_COLUMNS):
            output_df.insert(insert_position + offset, column, column_data[column])
        return output_df

    def _build_unmatched_dataframe(self, output_df: pd.DataFrame) -> pd.DataFrame:
        unmatched_series = output_df.loc[
            output_df["pathogen_name"].isna(),
            "pathogen_old",
        ]
        cleaned_values = [
            self._clean_text(value)
            for value in unmatched_series.dropna().astype(str).tolist()
            if self._normalize_text(value)
        ]
        counts = Counter(cleaned_values)
        rows = [
            {"pathogen_old": name, "count": count}
            for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        ]
        return pd.DataFrame(rows, columns=["pathogen_old", "count"])

    def _to_prompt_candidate(
        self,
        prompt_index: int,
        record_index: int,
    ) -> dict[str, Any]:
        record = self._records[record_index]
        return {
            "index": prompt_index,
            "pathogen_name": record["pathogen_name"],
            "pathogen": record["pathogen"],
            "pathogen_rank_1": record["pathogen_rank_1"],
            "pathogen_rank_2": record["pathogen_rank_2"],
            "pathogen_alias": record["pathogen_alias"],
        }

    def _decision_from_dict(self, payload: dict[str, Any]) -> MatchDecision:
        pathogen_name = payload.get("pathogen_name")
        record = self._records_by_name.get(pathogen_name) if pathogen_name else None
        return MatchDecision(
            matched=bool(payload.get("matched")),
            pathogen_name=pathogen_name,
            pathogen_alias=payload.get("pathogen_alias") or (record.get("pathogen_alias") if record else None),
            pathogen=payload.get("pathogen") or (record.get("pathogen") if record else None),
            pathogen_rank_1=payload.get("pathogen_rank_1") or (record.get("pathogen_rank_1") if record else None),
            pathogen_rank_2=payload.get("pathogen_rank_2") or (record.get("pathogen_rank_2") if record else None),
            reason=str(payload.get("reason") or "cached"),
            source=str(payload.get("source") or "cache"),
        )

    def _decision_to_dict(self, decision: MatchDecision) -> dict[str, Any]:
        return {
            "matched": decision.matched,
            "pathogen_name": decision.pathogen_name,
            "pathogen_alias": decision.pathogen_alias,
            "pathogen": decision.pathogen,
            "pathogen_rank_1": decision.pathogen_rank_1,
            "pathogen_rank_2": decision.pathogen_rank_2,
            "reason": decision.reason,
            "source": decision.source,
        }

    def _record_to_decision(
        self,
        record: dict[str, Any],
        reason: str,
        source: str,
    ) -> MatchDecision:
        return MatchDecision(
            matched=True,
            pathogen_name=record.get("pathogen_name"),
            pathogen_alias=record.get("pathogen_alias"),
            pathogen=record.get("pathogen"),
            pathogen_rank_1=record.get("pathogen_rank_1"),
            pathogen_rank_2=record.get("pathogen_rank_2"),
            reason=reason,
            source=source,
        )

    def _load_cache(self) -> dict[str, Any]:
        if not self.cache_path.exists():
            return {}
        try:
            return json.loads(self.cache_path.read_text(encoding="utf-8"))
        except Exception as exc:
            self.logger.warning("缓存文件读取失败，将忽略旧缓存：%s", exc)
            return {}

    def _save_cache(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(
            json.dumps(self._cache, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _extract_json_object(self, content: str) -> dict[str, Any]:
        text = content.strip()
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
        if fenced:
            text = fenced.group(1)
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError(f"模型未返回 JSON 对象：{content}")
        return json.loads(text[start:end + 1])

    def _merge_indices(self, primary: list[int], secondary: list[int]) -> list[int]:
        merged: list[int] = []
        seen: set[int] = set()
        for index in primary + secondary:
            if index not in seen:
                merged.append(index)
                seen.add(index)
            if len(merged) >= self.candidate_limit:
                break
        return merged

    def _validate_columns(
        self,
        dataframe: pd.DataFrame,
        required_columns: list[str],
        file_name: str,
    ) -> None:
        missing = [
            column
            for column in required_columns
            if column not in dataframe.columns
        ]
        if missing:
            missing_text = ", ".join(missing)
            raise ValueError(f"文件缺少必要列：{file_name} -> {missing_text}")

    def _clean_optional_text(self, value: Any) -> str | None:
        if pd.isna(value):
            return None
        text = self._clean_text(value)
        return text or None

    def _clean_text(self, value: Any) -> str:
        if value is None:
            return ""
        text = str(value).strip()
        return text

    def _split_aliases(self, value: Any) -> list[str]:
        alias_text = self._clean_text(value)
        if not alias_text:
            return []
        aliases: list[str] = []
        for alias in alias_text.split(";"):
            normalized_alias = self._normalize_text(alias)
            if normalized_alias:
                aliases.append(normalized_alias)
        return aliases

    def _normalize_text(self, value: Any) -> str:
        text = self._clean_text(value)
        if not text:
            return ""
        text = unicodedata.normalize("NFKC", text).lower()
        text = text.replace("_", " ")
        text = re.sub(r"[^\w\s-]", " ", text)
        text = re.sub(r"[-/]+", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text
