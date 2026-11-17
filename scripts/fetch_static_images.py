"""현 사이트(WordPress)의 정적 페이지용 이미지를 내려받아 WebP로 변환합니다.

    uv run --with pillow scripts/fetch_static_images.py

원본은 var/source-img/ (git 제외), 결과는 app/static/img/ 에 저장합니다.
쇼룸 이미지는 이 스크립트가 아니라 wp_import.py에서 /data/media/public 으로 옮깁니다.
"""

import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "var" / "source-img"
OUT_DIR = ROOT / "app" / "static" / "img"
BASE = "https://www.goodpackage.co.kr/wp-content/uploads/"

# 저장 이름: (원본 경로, 최대 가로 px)
IMAGES: dict[str, tuple[str, int]] = {
    "logo": ("2024/05/logo-black.png", 400),
    "logo-white": ("2024/05/logo.png", 400),
    "logo-big": ("2024/05/big-logo.png", 600),
    "favicon": ("2024/05/파비콘.png", 512),
    "hero": ("2024/06/main-bg.jpg", 1920),
    "cta-bg": ("2024/06/main-bg-2.jpg", 1920),
    "footer-bg": ("2024/06/footer-bg.jpg", 1920),
    "biz-design": ("2024/06/패키지디자인.png", 240),
    "biz-facility": ("2024/06/최신제작설비.png", 240),
    "biz-quick": ("2024/06/빠른견적문의.png", 240),
    "company-bg": ("2024/06/companybg.jpg", 1920),
    "process-bg": ("2024/05/product-bg.jpg", 1920),
    "facilities-bg": ("2024/05/tech-bg2.png", 1920),
    "fac-printer": ("2024/05/인쇄기.png", 1000),
    "fac-coater": ("2024/05/코팅기.png", 1000),
    "fac-gluer": ("2024/05/접착기.png", 1000),
    "fac-cutter": ("2024/05/종이재단기.png", 1000),
    "fac-thomson": ("2024/05/톰슨기.png", 1000),
    "fac-sampler": ("2024/05/샘플기.png", 1000),
}


def download(rel: str) -> Path:
    dest = SRC_DIR / rel
    if dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = BASE + urllib.parse.quote(rel)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as res:
        dest.write_bytes(res.read())
    return dest


def convert(src: Path, name: str, max_w: int) -> Path:
    out = OUT_DIR / f"{name}.webp"
    with Image.open(src) as im:
        im = im.convert("RGBA") if im.mode in ("P", "LA", "RGBA") else im.convert("RGB")
        if im.width > max_w:
            im = im.resize((max_w, round(im.height * max_w / im.width)), Image.LANCZOS)
        im.save(out, "WEBP", quality=82, method=6)
    return out


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, (rel, max_w) in IMAGES.items():
        src = download(rel)
        out = convert(src, name, max_w)
        with Image.open(out) as im:
            size = f"{im.width}x{im.height}"
        src_kb, out_kb = src.stat().st_size // 1024, out.stat().st_size // 1024
        print(f"{name:18} {src_kb:>6}KB → {out_kb:>5}KB  {size}")


if __name__ == "__main__":
    main()
