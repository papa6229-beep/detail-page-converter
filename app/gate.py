"""게이트와 불변식 — DESIGN.md 5장.

케이스는 무한하지만 불변식은 유한하다. 통과하지 못한 변환은 내보내지 않고
사유 코드와 함께 보류 풀로 보낸다. **보류는 실패가 아니라 정상 동작이다.**
"""

from __future__ import annotations

from dataclasses import dataclass, field

# 5.3 보류 사유 코드
NO_BODY_IMAGE = "NO_BODY_IMAGE"
NO_CAPTION_MULTI_IMG = "NO_CAPTION_MULTI_IMG"
AREA_LOSS = "AREA_LOSS"
CAPTION_TRUNCATED = "CAPTION_TRUNCATED"
PANEL_GEOMETRY = "PANEL_GEOMETRY"
PROXIMITY_INVERTED = "PROXIMITY_INVERTED"
OPTION_UNMAPPABLE = "OPTION_UNMAPPABLE"
IMAGE_MISSING = "IMAGE_MISSING"

REASON_TEXT = {
    NO_BODY_IMAGE: "본문 이미지 없음",
    NO_CAPTION_MULTI_IMG: "이미지 다수 + 캡션 0",
    AREA_LOSS: "면적 손실 임계 초과",
    CAPTION_TRUNCATED: "캡션 문장이 끊김",
    PANEL_GEOMETRY: "조각 기하 이상",
    PROXIMITY_INVERTED: "유닛 안 간격이 유닛 사이보다 큼",
    OPTION_UNMAPPABLE: "옵션을 유닛에 배분 불가",
    IMAGE_MISSING: "원본 이미지를 못 받음",
}


#: 문장을 맺는 글자. 곧은 따옴표를 큰따옴표 문자열 안에 쓰려다 리터럴이 거기서
#: 끊겨 `"` 와 `'` 가 조용히 빠져 있었다. 목록으로 적으면 그런 일이 안 생긴다.
SENTENCE_END = frozenset('.。!?…"\'’”)]』」》')


@dataclass
class Verdict:
    ok: bool = True
    reasons: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def fail(self, code: str, note: str = "") -> None:
        self.ok = False
        if code not in self.reasons:
            self.reasons.append(code)
        if note:
            self.notes.append(f"{code}: {note}")

    def note(self, code: str, text: str = "") -> None:
        """보류시키지 않고 적어만 둔다.

        보류는 **사람이 손봐야 한다**는 뜻이어야 한다. 우리 규칙이 예민해서 켜지는
        빨간불이 섞이면 빨간불 전체를 아무도 안 믿게 되고, 진짜 깨진 상품이
        그 틈으로 지나간다.
        """
        self.notes.append(f"{code}: {text}" if text else code)

    @property
    def text(self) -> str:
        return " · ".join(REASON_TEXT.get(r, r) for r in self.reasons)


def pre_gate(images: list[str], n_captions: int, n_options: int) -> Verdict:
    """사전 게이트 — 엑셀만 보고, 이미지를 받기 전에. 비용이 0이다 (5.2)."""
    v = Verdict()
    if not images:
        v.fail(NO_BODY_IMAGE, "상품 이미지가 한 장도 없다")
        return v
    # 캡션 없는 여러 장은 **정상이다** — 적어만 두고 보류시키지 않는다.
    #
    #   없는 것은 유닛이 아니라 캡션이다 (3.1). 글 없이 광고컷만 늘어놓은 원본이
    #   779행에 12개 있고, 그런 페이지는 그림을 순서대로 크게 싣는 것이 정답이다.
    #   실물 49개에서 이 규칙은 2495239 · 2495240 둘을 빨강으로 켰고 **둘 다
    #   멀쩡했다** — 히어로 · 광고컷 6~8장 · 푸터로 제대로 나왔다.
    #   CAPTION_TRUNCATED 와 같은 자리다. 사람이 손댈 것이 없으면 빨간불이 아니다.
    if len(images) >= 6 and n_captions == 0:
        v.note(NO_CAPTION_MULTI_IMG, f"이미지 {len(images)}장인데 캡션이 0개")
    if n_options and len(images) > 1 and n_options > len(images):
        v.fail(OPTION_UNMAPPABLE, f"옵션 {n_options}종 > 유닛 {len(images)}개")
    return v


def post_check(product, ink_coverage: float | None = None, gap_stats=None) -> Verdict:
    """사후 검증 — 변환 후 불변식 (5.1)."""
    v = Verdict()
    units = product.units

    if not units and not product.ad:
        v.fail(NO_BODY_IMAGE, "유닛이 하나도 나오지 않았다")
        return v

    # ① 면적 보존
    if ink_coverage is not None and ink_coverage < 0.97:
        v.fail(AREA_LOSS, f"잉크 보존율 {ink_coverage:.3f}")

    # ③ 캡션이 문장 중간에 끊기지 않음 — **적어만 두고 보류시키지 않는다**
    #
    #    실물 49개에서 이 규칙은 다섯 상품을 보류시켰고 **다섯 다 오경보**였다.
    #      2494955  …"나의 생 삽입 아이돌"   곧은 따옴표가 아래 목록에서 먹혀 있었다
    #      2495652/3/4  …자극의 파도를 가져온다   마침표 없이 끝나는 원본 문체
    #      2495671  …미니멈 메이드] 단면도    라벨이지 문장이 아니다
    #    잡으려던 것은 분할 실패인데 실제로 잡는 것은 원본 저자의 문체와 라벨이다.
    #    한국어 상품 문구는 마침표 없이 끝나는 일이 흔하다.
    for u in product.captioned:
        text = u.caption.strip()
        if text and text[-1] not in SENTENCE_END and len(text) > 20:
            v.note(CAPTION_TRUNCATED, f"…{text[-14:]}")
            break

    # ④ 조각의 종횡비·최소 크기
    for u in units:
        if u.width and u.height:
            if min(u.width, u.height) < 24:
                v.fail(PANEL_GEOMETRY, f"{u.width}x{u.height}")
                break
            ratio = max(u.width, u.height) / max(1, min(u.width, u.height))
            if ratio > 24:
                v.fail(PANEL_GEOMETRY, f"종횡비 {ratio:.0f}:1")
                break

    # ⑤ 캡션 수 ≤ 이미지 수
    if len(product.captioned) > len(units):
        v.fail(OPTION_UNMAPPABLE, "캡션이 이미지보다 많다")

    # ⑥ 유닛 안 간격 < 유닛 사이 간격
    #    조각이 다 살아 있고 묶음만 틀린 경우는 ①로 잡히지 않는다.
    for gs in gap_stats or []:
        if gs.separated and gs.narrow and gs.wide and max(gs.narrow) >= min(gs.wide):
            v.fail(PROXIMITY_INVERTED, f"안 {max(gs.narrow)}px ≥ 사이 {min(gs.wide)}px")
            break

    # 옵션 배분 가능성
    n_opt = len(product.meta.options)
    if n_opt and product.option_units and len(product.option_units) != n_opt:
        v.notes.append(f"옵션 {n_opt}종 / 태그 붙은 유닛 {len(product.option_units)}개 — 확인 필요")

    return v
