"""고치기 전후를 파일 단위로 견준다.

    python compare_runs.py save 기준선.zip docs/baseline.json    ← 기준선 박아두기
    python compare_runs.py docs/baseline.json 이번회차.zip        ← 견주기

기준선을 zip 으로만 들고 있으면 잃어버린다. 뼈대만 뽑아 `baseline.json` 으로
저장소에 넣어 둔다 — 몇백 KB 라 git 에 들어가고, 나중에 "그때는 이랬다" 를
커밋 기록으로 확인할 수 있다. 견줄 때는 이번 회차 zip 하나만 있으면 된다.

**테스트가 못 지키는 것을 이것이 지킨다.** 테스트는 내가 상상한 경우만 지키고,
실물 50개는 내가 상상 못 한 것을 갖고 있다. `option_tag` 한 줄을 고쳤을 때
테스트 76개는 전부 통과했는데 옵션 사진 배치가 무너졌다. 그때 이것이 있었다면
`2470056.html 달라짐` 한 줄로 즉시 보였다.

쓰는 법은 한 가지다 — **고치려던 상품만 달라졌으면 통과, 아니면 되돌린다.**

문구 자동 채우기는 꺼 두고 만들어야 한다. 모델 문구는 돌릴 때마다 조금씩 달라서
켜 두면 전부 "달라짐" 으로 뜨고, 우리 코드가 바꾼 것이 그 안에 묻힌다.
(화면의 `문구는 원본 그대로 (기준선용)` 체크박스)
"""

from __future__ import annotations

import html
import re
import sys
import zipfile
from collections import Counter
from pathlib import Path

#: 그림은 견주지 않는다. data URI 가 파일의 99% 라 눈으로 볼 수 없고,
#: 우리가 고치는 것은 배치와 글이지 원본 그림이 아니다(그건 손대지 않는다).
IMG_RE = re.compile(r'data:image/[^"\']+')
TAG_RE = re.compile(r"<[^>]+>")


def unwrap(s: str) -> str:
    # `\r` 는 내용이 아니다. 윈도우에서 저장한 회차와 리눅스에서 저장한 회차를
    # 견주면 이것 때문에 전부 "달라짐" 으로 뜬다.
    return html.unescape(TAG_RE.sub("", s)).replace("\r", "").strip()


def load(where: str) -> dict[str, dict]:
    """폴더 · zip · 저장해 둔 baseline.json 어느 쪽이든 {상품번호: 뼈대} 로 읽는다."""
    import json

    p = Path(where)
    if p.suffix.lower() == ".json":
        return json.loads(p.read_text(encoding="utf-8"))

    docs: dict[str, str] = {}
    if p.is_dir():
        for f in sorted(p.glob("*.html")):
            docs[f.stem] = f.read_text(encoding="utf-8", errors="replace")
    elif p.suffix.lower() == ".zip":
        with zipfile.ZipFile(p) as z:
            for name in sorted(z.namelist()):
                if name.lower().endswith(".html"):
                    docs[Path(name).stem] = z.read(name).decode("utf-8", "replace")
    else:
        raise SystemExit(f"폴더 · zip · baseline.json 중 하나를 주세요: {where}")
    return {code: shape(doc) for code, doc in docs.items()}


def shape(doc: str) -> dict:
    """페이지의 뼈대만 뽑는다. 달라진 곳을 사람이 읽을 수 있어야 한다."""
    body = doc[doc.find('<div class="page">') :]
    flat = IMG_RE.sub("", body)
    heads = re.findall(r'class="feature__head">(.*?)</h3>', body, re.S)
    return {
        "섹션": " ".join(re.findall(r'<(?:section|header|footer)[^>]*class="([a-z]+)', body)),
        "그림": dict(Counter(re.findall(r'<figure class="([a-z_-]+)"', body))),
        "옵션카드": [unwrap(m) for m in re.findall(r'<p class="variant__name">(.*?)</p>', body, re.S)],
        "옵션묶음": [unwrap(m) for m in re.findall(r'<h3 class="optset__name">(.*?)</h3>', body, re.S)],
        # JSON 을 거쳐도 같아야 하므로 튜플이 아니라 리스트로 담는다.
        # 튜플로 두면 저장한 기준선과 방금 뽑은 것이 늘 "다름" 으로 나온다.
        "스펙": [
            [unwrap(k), unwrap(v), unwrap(u)]
            for k, v, u in re.findall(
                r'spec__k">(.*?)</p>.*?spec__v">(.*?)<span class="spec__u">(.*?)</span>', body, re.S
            )
        ],
        "특징수": len(re.findall(r'<article class="feature', body)),
        "소제목수": len(heads),
        "소제목": [unwrap(h) for h in heads],
        "강조수": body.count('class="em"'),
        "글자": unwrap(flat),
    }


def diff_one(a: dict, b: dict) -> list[str]:
    out = []
    for key in ("섹션", "그림", "옵션카드", "옵션묶음", "스펙", "특징수", "소제목수", "강조수"):
        if a[key] != b[key]:
            out.append(f"      {key}: {a[key]}  →  {b[key]}")
    if a["소제목"] != b["소제목"]:
        old, new = set(a["소제목"]), set(b["소제목"])
        for t in list(old - new)[:3]:
            out.append(f"      소제목 빠짐: {t[:70]}")
        for t in list(new - old)[:3]:
            out.append(f"      소제목 생김: {t[:70]}")
    if a["글자"] != b["글자"]:
        # 뼈대가 달라졌어도 글자는 따로 본다. 한 번의 수정이 둘 다 바꿀 수 있고,
        # 그때 글자 쪽을 감추면 무엇이 달라졌는지 절반만 보게 된다.
        import difflib

        sm = difflib.SequenceMatcher(None, a["글자"], b["글자"])
        out.append(f"      글자 달라짐 (닮음 {sm.ratio():.3f})")
        shown = 0
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                continue
            out.append(f"        {a['글자'][i1:i2][:60]!r} → {b['글자'][j1:j2][:60]!r}")
            shown += 1
            if shown >= 4:
                out.append("        …")
                break
    return out


def main() -> int:
    import json

    if len(sys.argv) >= 2 and sys.argv[1] == "save":
        if len(sys.argv) < 4:
            print("  python compare_runs.py save 기준선.zip docs/baseline.json")
            return 1
        data = load(sys.argv[2])
        out = Path(sys.argv[3])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n  기준선 {len(data)}개를 {out} 에 박았습니다 ({out.stat().st_size // 1024}KB)\n")
        return 0

    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    old, new = load(sys.argv[1]), load(sys.argv[2])

    only_old = sorted(set(old) - set(new))
    only_new = sorted(set(new) - set(old))
    both = sorted(set(old) & set(new))

    same, changed = [], []
    for code in both:
        a, b = old[code], new[code]
        (same if a == b else changed).append((code, a, b))

    print()
    print(f"  기준선 {len(old)}개 · 이번 {len(new)}개 · 견준 것 {len(both)}개")
    print("  " + "─" * 64)
    print(f"  같음 {len(same)}개 · 달라짐 {len(changed)}개")
    if only_old:
        print(f"  기준선에만 있음: {', '.join(only_old)}")
    if only_new:
        print(f"  이번에만 있음: {', '.join(only_new)}")
    print()

    for code, a, b in changed:
        print(f"  ● {code}")
        for line in diff_one(a, b):
            print(line)
    if not changed:
        print("  달라진 것이 없습니다.")
    print()
    print("  볼 것: **고치려던 상품만** 달라졌는가. 아니면 그 커밋을 되돌린다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
