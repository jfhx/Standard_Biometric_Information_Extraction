import argparse
import json
import logging
import sys
from pathlib import Path

from pathogen_mapping.config import (
    DEFAULT_CACHE_PATH,
    DEFAULT_DICT_PATH,
    DEFAULT_INPUT_PATH,
    DEFAULT_LOG_PATH,
    DEFAULT_MODEL_NAME,
    DEFAULT_MODEL_URL,
    DEFAULT_OUTPUT_PATH,
    DEFAULT_STATUS_TABLE_PATH,
    DEFAULT_UNMATCHED_PATH,
    MODEL_MAX_RETRIES,
    MODEL_TIMEOUT_SECONDS,
)
from pathogen_mapping.llm_client import LLMClient
from pathogen_mapping.logging_utils import configure_logging
from pathogen_mapping.matcher import PathogenMatcher
from pathogen_mapping.status_table import (
    MatchStatusTable,
    build_fallback_metadata,
    load_match_status_metadata,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Match pathogen_old values to the standard pathogen dictionary.",
    )
    parser.add_argument(
        "--input-path",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help="Input workbook path.",
    )
    parser.add_argument(
        "--dict-path",
        type=Path,
        default=DEFAULT_DICT_PATH,
        help="Dictionary workbook path.",
    )
    parser.add_argument(
        "--output-path",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Matched output workbook path.",
    )
    parser.add_argument(
        "--unmatched-path",
        type=Path,
        default=DEFAULT_UNMATCHED_PATH,
        help="Unmatched pathogen_old workbook path.",
    )
    parser.add_argument(
        "--cache-path",
        type=Path,
        default=DEFAULT_CACHE_PATH,
        help="LLM match cache path.",
    )
    parser.add_argument(
        "--log-path",
        type=Path,
        default=DEFAULT_LOG_PATH,
        help="Run log path.",
    )
    parser.add_argument(
        "--status-table-path",
        type=Path,
        default=DEFAULT_STATUS_TABLE_PATH,
        help="Real-time status table path.",
    )
    parser.add_argument(
        "--model-url",
        default=DEFAULT_MODEL_URL,
        help="Model endpoint.",
    )
    parser.add_argument(
        "--model-name",
        default=DEFAULT_MODEL_NAME,
        help="Model name.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=MODEL_TIMEOUT_SECONDS,
        help="Model request timeout in seconds.",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=MODEL_MAX_RETRIES,
        help="Max retries for model requests.",
    )
    parser.add_argument(
        "--candidate-limit",
        type=int,
        default=25,
        help="Candidate limit sent to the model.",
    )
    parser.add_argument(
        "--skip-connection-test",
        action="store_true",
        help="Skip model connection test before matching.",
    )
    parser.add_argument(
        "--test-connection-only",
        action="store_true",
        help="Only test model connectivity and exit.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    configure_logging(args.log_path)
    logger = logging.getLogger("main")
    logger.info("Task started.")

    status_table: MatchStatusTable | None = None
    if not args.test_connection_only:
        try:
            metadata = load_match_status_metadata(args.input_path)
        except Exception as exc:
            logger.warning("Failed to load status table metadata, using fallback metadata: %s", exc)
            metadata = build_fallback_metadata(args.input_path)

        try:
            status_table = MatchStatusTable(args.status_table_path, metadata)
            status_table.mark_started()
            logger.info("Status table initialized: %s", args.status_table_path)
        except Exception:
            logger.exception("Failed to initialize status table")
            status_table = None

    client = LLMClient(
        endpoint=args.model_url,
        model_name=args.model_name,
        timeout_seconds=args.timeout_seconds,
        max_retries=args.max_retries,
    )

    try:
        if not args.skip_connection_test or args.test_connection_only:
            test_response = client.test_connection()
            logger.info("Model connection test succeeded: %s", test_response)

        if args.test_connection_only:
            print("Model connection test succeeded.")
            return 0

        matcher = PathogenMatcher(
            llm_client=client,
            cache_path=args.cache_path,
            candidate_limit=args.candidate_limit,
        )
        summary = matcher.run(
            input_path=args.input_path,
            dict_path=args.dict_path,
            output_path=args.output_path,
            unmatched_path=args.unmatched_path,
        )
        summary["status_table_path"] = str(args.status_table_path)

        if status_table is not None:
            try:
                status_table.mark_finished(summary)
            except Exception:
                logger.exception("Failed to write final status table rows")

        logger.info("Task completed: %s", json.dumps(summary, ensure_ascii=False))
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        if status_table is not None:
            try:
                status_table.mark_failed(exc)
            except Exception:
                logger.exception("Failed to write failure status row")
        logger.exception("Task failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
