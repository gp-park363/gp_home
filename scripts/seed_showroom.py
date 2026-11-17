"""현 사이트 쇼룸(공개 페이지)을 파싱해 portfolio_items / portfolio_images 로 넣습니다.

    make seed-showroom                       # web 컨테이너에서 실행
    python -m scripts.seed_showroom --html 파일.html   # 저장해 둔 HTML로 실행

- 쇼룸 데이터는 KBoard가 아니라 The Grid(목록) + Popup Builder(사양 팝업) 글에 있습니다.
  그리드 항목 tg-post-{ID}와 팝업 sgpb-popup-builder-content-{ID}가 같은 WP 글 ID를 씁니다.
- wp_post_id 기준으로 덮어쓰므로 여러 번 실행해도 결과가 같습니다.
- 이미지는 WebP로 변환해 MEDIA_ROOT/public/portfolio/ 에 원본 URL 해시 이름으로 저장합니다.
- 박스형태·업종은 현 사이트에 없는 분류라 아래 CLASSIFY 표로 정합니다(관리자에서 수정 가능 예정).
"""

import argparse
import hashlib
import html
import io
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from PIL import Image
from sqlalchemy import select

from app.config import get_settings
from app.content import BOX_TYPES, INDUSTRIES
from app.db import SessionLocal
from app.models import PortfolioImage, PortfolioItem

SOURCE_URL = "https://www.goodpackage.co.kr/portfolio/"
SITE = "https://www.goodpackage.co.kr"
UA = {"User-Agent": "Mozilla/5.0 (goodpackage migration)"}
MAX_WIDTH = 1600

# 품번 → (박스형태, 업종). 형태 원문과 품명을 보고 정한 값입니다.
CLASSIFY: dict[str, tuple[str, str]] = {
    "GP1001": ("lid", "food"),  # 롤리팝 선물상자 — 맞뚜껑, 패드
    "GP1002": ("lid", "living"),  # 인사덴트 칫솔 — 걸이형 맞뚜껑
    "GP1003": ("assembly", "cosmetics"),  # 클렌징 오일 — 조립덮개형
    "GP1004": ("lid", "electronics"),  # 충전기 — 걸이형 맞뚜껑
    "GP1005": ("rrp", "living"),  # 템포 RRP
    "GP1006": ("assembly", "food"),  # 브뤼셀 초콜렛 — 상단 덮개, 하부조립
    "GP1007": ("custom", "cosmetics"),  # 메이크업 쿠션 — 3면뚜껑
    "GP1008": ("assembly", "food"),  # 게딱지장 — 상단 뚜껑, 하부조립
    "GP1009": ("sleeve", "health"),  # 솔가 선물세트 — Y형 상하짝, 슬리브
    "GP1010": ("assembly", "cosmetics"),  # 스파클링 화장품 — 완전조립
    "GP1011": ("cover", "health"),  # 홍삼정 싸바리 — 표지싸바리
    "GP1012": ("b", "electronics"),  # CCTV — B형
    "GP1013": ("assembly", "cosmetics"),  # 앰플 세럼 세트 — 조립덮개형
    "GP1014": ("lid", "food"),  # 고까스 — 변형된 맞뚜껑
    "GP1015": ("assembly", "food"),  # 케익상자 — 조립형
    "GP1016": ("b", "living"),  # 목욕스폰지 — B형
    "GP1017": ("custom", "health"),  # 엘아르기맥스 — 3면뚜껑
    "GP1018": ("lid", "health"),  # 편안타 — 맞뚜껑
    "GP1019": ("sleeve", "food"),  # 망고젤리 — 슬리브
    "GP1020": ("lid", "cosmetics"),  # 헬로스킨 튜브 — 패드일체형 맞뚜껑
    "GP1021": ("lid", "electronics"),  # 차량용 충전기 — 맞뚜껑
    "GP1022": ("lid", "living"),  # 컨택트 렌즈 — 맞뚜껑
    "GP1023": ("lid", "cosmetics"),  # 스팟 세럼 — 맞뚜껑
    "GP1025": ("sabari", "cosmetics"),  # 레드톡스 마스크 — 싸바리
    "GP1026": ("handle", "electronics"),  # 대형 공구상자 — B형 + 일체형 손잡이
    "GP1027": ("sleeve", "cosmetics"),  # 기능성 화장품 — Y형, 슬리브
    "GP1029": ("g", "food"),  # 제과박스 — G형
    "GP1030": ("g", "food"),  # 양갱박스 — G형
    "GP1031": ("sabari", "living"),  # 와인잔박스 — 싸바리
    "GP1032": ("sabari", "food"),  # 육포선물박스 — 싸바리
    "GP1033": ("sabari", "etc"),  # 매트샘플박스 — 3중싸바리
    "GP1034": ("sabari", "electronics"),  # 전자제품박스 — 브이컷싸바리
    "GP1035": ("b", "cosmetics"),  # 앰플박스 — B형(바닥조립)
    "GP1036": ("custom", "food"),  # 케잌박스 — 4면접착형
    "GP1037": ("assembly", "food"),  # 초콜릿박스 — 완전조립형
    "GP1038": ("b", "food"),  # 커피박스 — B형(3면접착)
    "GP1039": ("lid", "living"),  # 비누박스 — 맞뚜껑형
}

SPEC_KEYS = {
    "품명": "name",
    "품번": "code",
    "형태": "shape",
    "재질": "material",
    "인쇄": "printing",
    "코팅": "coating",
    "후가공": "finishing",
    "박스설명": "description",
}


@dataclass
class Parsed:
    wp_post_id: int
    fields: dict[str, str]
    images: list[str] = field(default_factory=list)
    thumb: str | None = None  # 그리드 카드 이미지 (400x300)


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as res:
        return res.read()


def absolute(src: str) -> str:
    return src if src.startswith("http") else SITE + src


def parse(page: str) -> list[Parsed]:
    # 그리드 순서(최신 글이 앞)와 카드 이미지
    grid_ids = list(dict.fromkeys(int(i) for i in re.findall(r"tg-item tg-post-(\d+)", page)))
    thumbs = {
        int(pid): absolute(src)
        for pid, src in re.findall(
            r'tg-item tg-post-(\d+).*?<img class="tg-item-image"[^>]*src="([^"]+)"', page, re.S
        )
    }

    # 팝업마다 끝 표시가 일정하지 않아, 팝업 시작 위치 사이를 한 덩어리로 자릅니다.
    starts = list(
        re.finditer(r'sgpb-popup-builder-content-(\d+) sgpb-popup-builder-content-html"', page)
    )
    popups: dict[int, Parsed] = {}
    for n, m in enumerate(starts):
        end = starts[n + 1].start() if n + 1 < len(starts) else len(page)
        pid, body = int(m.group(1)), page[m.end() : end]
        if "showroom_info" not in body:  # 목형 배너 등 다른 팝업
            continue
        body = body.split("showroom_btn")[0]
        fields = {}
        for dt, dd in re.findall(r"<dt>(.*?)</dt>\s*<dd>(.*?)</dd>", body, re.S):
            key = SPEC_KEYS.get(html.unescape(dt).strip())
            if key:
                fields[key] = html.unescape(re.sub(r"<[^>]+>", "", dd)).strip()
        # 대표 이미지(showroom_thumb) → 본문 사진 순서. 로고는 제외
        srcs = re.findall(r'<img[^>]+src="([^"]+/uploads/[^"]+)"', body)
        images = [absolute(s) for s in srcs if "logo" not in s]
        popups[pid] = Parsed(pid, fields, list(dict.fromkeys(images)))

    missing = [i for i in grid_ids if i not in popups]
    if missing:
        raise SystemExit(f"사양 팝업이 없는 그리드 항목: {missing}")
    for i in grid_ids:
        popups[i].thumb = thumbs.get(i)
    return [popups[i] for i in grid_ids]


def save_image(url: str) -> tuple[str, int, int]:
    """원본 URL 해시로 파일명을 정해, 이미 있으면 다시 받지 않습니다."""
    rel = f"portfolio/{hashlib.sha1(url.encode()).hexdigest()[:16]}.webp"
    dest = get_settings().media_public / rel
    if dest.exists():
        with Image.open(dest) as im:
            return rel, im.width, im.height
    dest.parent.mkdir(parents=True, exist_ok=True)
    quoted = urllib.parse.quote(url, safe=":/%")
    with Image.open(io.BytesIO(fetch(quoted))) as im:
        im = im.convert("RGBA") if im.mode in ("P", "LA", "RGBA") else im.convert("RGB")
        if im.width > MAX_WIDTH:
            im = im.resize((MAX_WIDTH, round(im.height * MAX_WIDTH / im.width)), Image.LANCZOS)
        im.save(dest, "WEBP", quality=82, method=6)
        return rel, im.width, im.height


def run(page: str) -> None:
    rows = parse(page)
    print(f"쇼룸 {len(rows)}건 파싱")
    with SessionLocal() as db:
        # 오래된 글부터 넣어 id 순서가 최신순과 맞도록 합니다.
        for row in reversed(rows):
            f = row.fields
            box_type, industry = CLASSIFY.get(f.get("code", ""), ("custom", "etc"))
            assert box_type in BOX_TYPES and industry in INDUSTRIES

            item = db.scalar(
                select(PortfolioItem).where(PortfolioItem.wp_post_id == row.wp_post_id)
            )
            if item is None:
                item = PortfolioItem(wp_post_id=row.wp_post_id)
                db.add(item)
            item.name = f.get("name", "")
            item.code = f.get("code") or None
            item.box_type, item.industry = box_type, industry
            for key in ("shape", "material", "printing", "coating", "finishing", "description"):
                setattr(item, key, f.get(key, ""))

            item.thumb_path = save_image(row.thumb)[0] if row.thumb else None
            item.images.clear()
            db.flush()
            for n, url in enumerate(row.images):
                rel, w, h = save_image(url)
                item.images.append(PortfolioImage(path=rel, width=w, height=h, sort_order=n))
            code, n_img = item.code or "-", len(row.images)
            print(f"  {code:7} {item.name:12} {box_type:9} {industry:11} 이미지 {n_img}")
        db.commit()
    print("완료")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--html", help="저장해 둔 쇼룸 HTML 파일 (기본: 현 사이트에서 내려받기)")
    args = ap.parse_args()
    if args.html:
        with open(args.html, encoding="utf-8") as fp:
            page = fp.read()
    else:
        page = fetch(SOURCE_URL).decode("utf-8")
    run(page)


if __name__ == "__main__":
    main()
