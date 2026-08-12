"""간격 이중구조 — DESIGN.md 4.3."""

from slicer.gaps import group_by_gaps, split_gaps


def test_두_무리로_갈리면_임계값을_스스로_찾는다():
    # 텐가 왼쪽 열의 실측 간격: 유닛 안 4·6px, 유닛 사이 24px
    gs = split_gaps([6, 4, 24, 6, 4, 24, 6, 4])
    assert gs.separated
    assert gs.threshold == 6
    assert set(gs.wide) == {24}
    assert set(gs.narrow) == {4, 6}


def test_한_무리면_자르지_않는다():
    # 칸 하나 안의 간격만 있을 때. 여기서 억지로 자르면 캡션이 떨어져 나간다.
    assert not split_gaps([6, 4, 4]).separated


def test_전부_같으면_자르지_않는다():
    assert not split_gaps([12, 12, 12]).separated


def test_간격이_하나뿐이면_자르지_않는다():
    # 오른쪽 4번째 칸: 사진이 짧게 끝나 간격이 31px 이지만 유닛은 하나다.
    assert not split_gaps([31]).separated


def test_0px_간격이_비를_무한대로_만들지_않는다():
    gs = split_gaps([0, 0, 1, 0])
    assert not gs.separated


def test_묶기는_넓은_간격에서만_끊는다():
    items = list("abcdef")
    groups, gs = group_by_gaps(items, [4, 6, 24, 4, 6])
    assert gs.threshold == 6
    assert groups == [["a", "b", "c"], ["d", "e", "f"]]


def test_묶을_것이_하나면_그대로():
    groups, _ = group_by_gaps(["a"], [])
    assert groups == [["a"]]


def test_간격_개수가_맞지_않으면_거부한다():
    try:
        group_by_gaps(["a", "b", "c"], [4])
    except ValueError:
        return
    raise AssertionError("간격 개수 불일치를 잡지 못했다")
