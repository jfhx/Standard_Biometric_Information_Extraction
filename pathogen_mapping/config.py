from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_MODEL_URL = "http://159.226.80.101:1045/v1/chat/completions"
DEFAULT_MODEL_NAME = "DeepSeek-V3"
DEFAULT_INPUT_PATH = BASE_DIR / "biometric_extracted_result_1000.xlsx"
DEFAULT_DICT_PATH = BASE_DIR / "dict_pathogen_feature.xlsx"
DEFAULT_OUTPUT_DIR = BASE_DIR / "outputs"
DEFAULT_OUTPUT_PATH = DEFAULT_OUTPUT_DIR / "biometric_extracted_result_1000_matched.xlsx"
DEFAULT_UNMATCHED_PATH = DEFAULT_OUTPUT_DIR / "unmatched_pathogen_old.xlsx"
DEFAULT_CACHE_PATH = DEFAULT_OUTPUT_DIR / "llm_match_cache.json"
DEFAULT_LOG_PATH = DEFAULT_OUTPUT_DIR / "run.log"
MODEL_TIMEOUT_SECONDS = 120
MODEL_MAX_RETRIES = 3
CANDIDATE_LIMIT = 25
RESULT_COLUMNS = [
    "pathogen_name",
    "pathogen_alias",
    "pathogen",
    "pathogen_rank_1",
    "pathogen_rank_2",
]
REQUIRED_INPUT_COLUMNS = ["pathogen_old"]
REQUIRED_DICT_COLUMNS = [
    "pathogen_name",
    "pathogen_alias",
    "pathogen",
    "pathogen_rank_1",
    "pathogen_rank_2",
]
