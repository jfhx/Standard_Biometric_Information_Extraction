import json
from typing import Any


SYSTEM_PROMPT = """你是一个极其谨慎的病原体名称标准化助手。
你的任务是判断原始病原体名称 pathogen_old 是否与候选列表中的某一个标准病原体全称 pathogen_name 指代同一个具体病原体。

字段含义：
1. pathogen_old：原始文本中的病原体名字，可能存在缩写、拼写错误、大小写差异、连字符差异、缺字母、旧名称、别名。
2. pathogen_name：标准病原体全称，是目标匹配字段。
3. pathogen_alias：该标准病原体的别名字段，多个别名用英文分号 ; 分隔。
   它与 pathogen_name 一一对应，只能在明确是同一个病原体别名时作为强证据。
4. pathogen：标准病原体简称。
5. pathogen_rank_1、pathogen_rank_2：标准病原体分类信息，只能作为辅助参考，不能因为分类相近就强行匹配。

你的原则：
1. 只有在明确是同一个病原体时才匹配。
2. 可以识别常见缩写、同义名称、明显拼写错误、大小写差异、单复数差异。
3. 如果 pathogen_old 命中的是某个 pathogen_alias，只有在这个 alias 明确、精准、无歧义地指向唯一标准病原体时才能匹配。
4. 绝不能把上位概念、下位概念、同属不同种、同科不同病原体、相近但不同的病毒株错误匹配成同一个。
5. 如果存在歧义、不确定、证据不足，必须返回不匹配。
6. 不能因为字符串长得像就匹配，必须看语义是否为同一个病原体。

你必须只输出一个 JSON 对象，不能输出任何额外说明文字。
"""


def build_match_messages(pathogen_old: str, candidate_records: list[dict[str, Any]]) -> list[dict[str, str]]:
    user_payload = {
        "task": "从候选标准病原体中选择与 pathogen_old 语义上完全对应的一项；如果没有准确对应项，则返回 no match。",
        "pathogen_old": pathogen_old,
        "candidates": candidate_records,
        "output_schema": {
            "matched": "bool，是否匹配成功",
            "matched_index": "int 或 null，对应 candidates 中的 index",
            "matched_pathogen_name": "string 或 null，必须与候选中的 pathogen_name 完全一致",
            "confidence": "high | medium | low",
            "reason": "简短原因，说明为什么匹配或为什么不匹配"
        },
        "hard_rules": [
            "如果不确定，就 matched=false。",
            "如果 pathogen_old 只是看起来像某个 alias，但不能高把握确认它就是该标准病原体的别名，则不能匹配。",
            "如果原始名称只是更高层级、更宽泛的病原体类别，而候选是更具体的成员，则不能匹配。",
            "如果候选中没有语义完全一致的标准病原体全称，则不能猜测。",
            "输出必须是 JSON 对象。"
        ]
    }
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, indent=2)},
    ]
