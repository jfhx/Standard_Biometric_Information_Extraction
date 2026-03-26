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
    DEFAULT_UNMATCHED_PATH,
    MODEL_MAX_RETRIES,
    MODEL_TIMEOUT_SECONDS,
)
from pathogen_mapping.llm_client import LLMClient
from pathogen_mapping.logging_utils import configure_logging
from pathogen_mapping.matcher import PathogenMatcher


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="使用 DeepSeek-V3 将 pathogen_old 匹配到标准病原体字典。"
    )
    parser.add_argument(
        "--input-path",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help="原始结果表路径",
    )
    parser.add_argument(
        "--dict-path",
        type=Path,
        default=DEFAULT_DICT_PATH,
        help="病原体字典表路径",
    )
    parser.add_argument(
        "--output-path",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="补齐后的输出 Excel 路径",
    )
    parser.add_argument(
        "--unmatched-path",
        type=Path,
        default=DEFAULT_UNMATCHED_PATH,
        help="未匹配 pathogen_old 汇总路径",
    )
    parser.add_argument(
        "--cache-path",
        type=Path,
        default=DEFAULT_CACHE_PATH,
        help="模型匹配缓存文件路径",
    )
    parser.add_argument(
        "--log-path",
        type=Path,
        default=DEFAULT_LOG_PATH,
        help="日志文件路径",
    )
    parser.add_argument(
        "--model-url",
        default=DEFAULT_MODEL_URL,
        help="DeepSeek-V3 接口地址",
    )
    parser.add_argument(
        "--model-name",
        default=DEFAULT_MODEL_NAME,
        help="模型名称",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=MODEL_TIMEOUT_SECONDS,
        help="模型请求超时时间（秒）",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=MODEL_MAX_RETRIES,
        help="模型请求失败后的最大重试次数",
    )
    parser.add_argument(
        "--candidate-limit",
        type=int,
        default=25,
        help="送给模型的候选病原体上限",
    )
    parser.add_argument(
        "--skip-connection-test",
        action="store_true",
        help="跳过启动前的模型连通性测试",
    )
    parser.add_argument(
        "--test-connection-only",
        action="store_true",
        help="只测试模型连接，不处理 Excel",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    configure_logging(args.log_path)
    logger = logging.getLogger("main")
    logger.info("启动任务：请确保调用所内模型前已退出 Clash。")

    client = LLMClient(
        endpoint=args.model_url,
        model_name=args.model_name,
        timeout_seconds=args.timeout_seconds,
        max_retries=args.max_retries,
    )

    try:
        if not args.skip_connection_test or args.test_connection_only:
            test_response = client.test_connection()
            logger.info("模型连接测试成功，响应内容：%s", test_response)

        if args.test_connection_only:
            print("模型连接测试成功。")
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
        logger.info(
            "任务完成：%s",
            json.dumps(summary, ensure_ascii=False),
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    except Exception:
        logger.exception("任务执行失败")
        return 1


if __name__ == "__main__":
    sys.exit(main())
