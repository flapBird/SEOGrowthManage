from __future__ import annotations

from datetime import timedelta

from ..config import get_settings
from ..models import KeywordCandidate, KeywordCandidateStatus, now_local


def is_worth_agent_review(candidate: KeywordCandidate) -> bool:
    """本地启发式过滤：在交给远程 Agent 前先剔除明显不值得花 MCP / search api 额度查的词。

    返回 False 的词会被跳过，不进入 Agent 批次。这一层纯本地、零外部依赖，
    先过滤掉大部分垃圾词（数字、泛词、冷却中、刚判过、低分），只把少数存活词送出去。

    复用 normalizer 已做的清洗（normalize_game_title 已在入库时过滤纯泛词/纯数字/噪声词），
    这里只补"是否值得现在送 Agent 再查一次"的判断。
    """
    settings = get_settings()
    kw = candidate.keyword or ""

    if len(kw) < 3:
        return False
    # 被 normalizer 漏过的纯数字 / 纯符号词。
    if kw.replace(" ", "").replace("-", "").isdigit():
        return False
    # 冷却中的 IGNORE 不浪费额度复查。
    if candidate.status == KeywordCandidateStatus.ignore and candidate.ignored_until \
            and candidate.ignored_until > now_local():
        return False
    # 最近刚被 Agent 判过，冷却期内不重复送（避免额度浪费在短期不变的判断上）。
    if candidate.agent_judged_at and \
            (now_local() - candidate.agent_judged_at) < timedelta(hours=settings.agent_review_cooldown_hours):
        return False
    # 本地评分极低，大概率不值得。
    if (candidate.total_score or 0) < settings.agent_min_score:
        return False
    return True
