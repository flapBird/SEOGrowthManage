from .base import ChannelAdapter
from .playwright_form import PlaywrightFormAdapter


ADAPTERS: dict[str, type[ChannelAdapter]] = {
    "playwright_form": PlaywrightFormAdapter,
}


def get_adapter(key: str | None) -> ChannelAdapter:
    if not key or key not in ADAPTERS:
        raise ValueError(f"未知或未配置的渠道适配器: {key or '空'}")
    return ADAPTERS[key]()

