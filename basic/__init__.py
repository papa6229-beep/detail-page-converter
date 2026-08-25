"""기본형 본문 변환기 (시제품).

    단순형(app/, slicer/)은 건드리지 않는다. 여기서 빌려 쓰는 것은 app.llm 뿐이다.

    흐름:  이미지 → bands.read (밴드·종류)  → sidetext (사진 옆 글자 떼기)
           → body.sections (섹션 묶기·번호)  → read_text (AI 1콜, 글자 읽기)
           → render (860px HTML)
"""
