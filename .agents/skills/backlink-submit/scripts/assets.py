#!/usr/bin/env python3
"""素材解析器：按用户约定从 assets/ 文件夹解析站点 icon 与截图。

约定（用户实际习惯，2026-09-30 确认）：
- 文件夹名 = 站点域名，**可以不带后缀**（如 thefreakcircus 对应 thefreakcircus.help），
  按前缀匹配
- icon：文件名以 icon 开头（通常 icon.png）
- 首页截图：优先 screenshot-1.png，其次截图工具原名（以 截屏/截图 开头的文件）
- 第二张截图：screenshot-2.png 或第二张 截屏/截图 文件
"""

from pathlib import Path

ASSETS_BASE = Path(__file__).parents[4] / "data" / "backlink_submit" / "assets"
IMG_EXTS = (".png", ".jpg", ".jpeg", ".webp")


def _images(folder: Path):
    return [f for f in sorted(folder.iterdir())
            if f.is_file() and f.suffix.lower() in IMG_EXTS]


def resolve(url_or_domain: str) -> dict:
    """返回 {"icon": path|None, "screenshots": [path, ...], "folder": path|None}。"""
    domain = url_or_domain.replace("https://", "").replace("http://", "")
    domain = domain.split("/")[0].removeprefix("www.").lower()
    folder = None
    if ASSETS_BASE.is_dir():
        if (ASSETS_BASE / domain).is_dir():
            folder = ASSETS_BASE / domain
        else:
            for d in sorted(ASSETS_BASE.iterdir()):
                if d.is_dir() and (domain.startswith(d.name) or d.name.startswith(domain.split(".")[0])):
                    folder = d
                    break
    if folder is None:
        return {"icon": None, "screenshots": [], "folder": None}

    files = _images(folder)
    icon = next((f for f in files if f.name.lower().startswith("icon")), None)
    std = [f for f in files if f.name.lower().startswith("screenshot")]
    cn = [f for f in files if f.name.startswith(("截屏", "截图"))]
    screenshots = []
    if std:
        screenshots.append(str(std[0]))
    elif cn:
        screenshots.append(str(cn[0]))
    second = std[1] if len(std) > 1 else (cn[1] if len(cn) > 1 else None)
    if second:
        screenshots.append(str(second))
    return {"icon": str(icon) if icon else None,
            "screenshots": screenshots,
            "folder": str(folder)}


if __name__ == "__main__":
    import sys
    for u in (sys.argv[1:] or ["https://thefreakcircus.help/"]):
        print(u, "→", resolve(u))
