"""Rebuilding a page-per-document scan (Internet Archive EPUBs) as a book."""

from __future__ import annotations

from book_creator import epub_reader, scanned as sc

BODY = ("the allied army marched on through the rain towards the river, and "
        "Marlborough rode ahead with the field-deputies to look at the ground")


def _book(pages_per_chapter: int = 6) -> list[tuple[str, bool]]:
    """A small scanned book: plate, title page, two chapters, an index."""
    pages = [("'JilJ3NVS0V^' ^miimi^ MUBRARY", False),     # bookplate, flagged
             ("THE WARS OF MARLBOROUGH BY FRANK TAYLOR", True)]
    n = 1
    for numeral, title in (("XVII", "ALMANZA, STOLLHOFEN, AND TOULON"),
                           ("XVIII", "HARLEY")):
        pages.append((f"{numeral}.— {title} On the morning {BODY}.", True))
        n += 1
        for _ in range(pages_per_chapter):
            head = f"{n} THE WARS OF MARLBOROUGH" if n % 2 == 0 else f"{title} {n}"
            pages.append((f"{head} {BODY}.", True))
            n += 1
    pages.append(("GENERAL INDEX Addison, Joseph, ii. 290", True))
    pages.append((f"GENERAL INDEX {n} Albemarle, Earl of, i. 44", True))
    return pages


# --------------------------------------------------------------------------- #
# Running heads and page numbers
# --------------------------------------------------------------------------- #
def test_running_heads_are_learned_from_their_recurrence():
    heads = sc.learn_heads([t for t, ok in _book() if ok])
    assert "THE WARS OF MARLBOROUGH" in heads and "HARLEY" in heads


def test_a_head_is_cut_with_its_page_number_on_either_side():
    heads = ["THE WARS OF MARLBOROUGH", "DUNKIRK, GHENT, AND BRUGES"]
    assert sc.strip_head("6 THE WARS OF MARLBOROUGH Marlborough to Godolphin", heads)[1] \
        == "Marlborough to Godolphin"
    assert sc.strip_head("DUNKIRK, GHENT, AND BRUGES 95 while his knowledge", heads)[1] \
        == "while his knowledge"


def test_page_numbers_as_ocr_misreads_them():
    heads = ["THE WARS OF MARLBOROUGH", "LILLE"]
    for page in ("loi", "l8i", "i6", "3i3", "no", "igS"):
        assert sc.strip_head(f"{page} THE WARS OF MARLBOROUGH the Elector", heads)[1] \
            == "the Elector", page
    # Run into the first word of the page.
    assert sc.strip_head("LILLE 153extent. Even with", heads)[1] == "extent. Even with"


def test_a_head_seen_before_is_cut_where_its_number_is_lost():
    """Left, "RACE WAR IN HIGH SCHOOL ZF disagreed" read as a chapter title."""
    heads, seen = ["RACE WAR IN HIGH SCHOOL"], set()
    sc.strip_head("14 RACE WAR IN HIGH SCHOOL C. O'Daly and the chapter", heads, seen)
    assert sc.strip_head("RACE WAR IN HIGH SCHOOL ZF disagreed we were", heads, seen)[1] \
        == "disagreed we were"


def test_a_heads_own_first_word_is_not_a_page_number():
    heads, seen = ["THE BEGINNING", "A subaltern’s war"], {"THE BEGINNING", "A subaltern’s war"}
    assert sc.strip_head("THE BEGINNING 19 We vied", heads, seen)[1] == "We vied"
    head, rest, numbered = sc.strip_head(
        "A SUBALTERN’S WAR CHAPTER I 1914 BEGINNING", heads, seen)
    assert rest.startswith("CHAPTER I") and not numbered


def test_a_head_in_small_capitals_is_learned_in_mixed_case():
    words = BODY.split()
    pages = [f"{n} A subaltern’s war {' '.join(words[n % 9:])}" if n % 2 == 0
             else f"THE SOMME {n} {' '.join(words[n % 7:])}" for n in range(10, 60)]
    assert "A subaltern’s war" in sc.learn_heads(pages)


def test_a_chapter_title_is_never_learned_as_a_head():
    """"APPENDIX I" looks like a head beside page number 1."""
    pages = [f"APPENDIX I {BODY}", f"APPENDIX II {BODY}", f"APPENDIX I {BODY}"]
    assert not any(h.startswith("APPENDIX") for h in sc.learn_heads(pages))


# --------------------------------------------------------------------------- #
# Chapters
# --------------------------------------------------------------------------- #
def test_chapters_come_from_the_books_own_headings():
    divisions, report = sc.rebuild(_book())
    assert [t for t, _ in divisions] == [
        "XVII. Almanza, Stollhofen, and Toulon", "XVIII. Harley"]
    assert report.unreadable == 1
    assert report.apparatus == ["General Index"]
    assert all("WARS OF MARLBOROUGH" not in b for _, b in divisions)
    assert divisions[0][1].startswith("On the morning")


def test_chapter_headings_in_the_forms_books_set_them():
    heads = ["MEMOIR OF FRANK TAYLOR"]
    cases = {
        "XIX.- DUNKIRK, GHENT, AND BRUGES The resolutions": "XIX.- DUNKIRK, GHENT, AND BRUGES",
        "XXL— LILLE On the morrow": "XXL— LILLE",
        "APPENDIX II SLANDER It has often": "APPENDIX II SLANDER",
        "MEMOIR OF FRANK TAYLOR When I think": "MEMOIR OF FRANK TAYLOR",
        "Chapter 2 Prelude By the time": "Chapter 2",
        "Appendix A LANE SCHOOL CENSUS 1958-1969 Non-white": "Appendix A LANE SCHOOL CENSUS 1958-1969",
        "CHAPTER II AN ADVENTURE ON THE SOMME § I One day": "CHAPTER II AN ADVENTURE ON THE SOMME",
    }
    for page, title in cases.items():
        assert sc.split_heading(page, heads)[0] == title, page


def test_a_sentence_is_not_a_heading():
    for page in ("the union chapter to demand a reduction",
                 "I was sure of it", "PREFACE 9 the fifteen million there were"):
        assert sc.split_heading(page, [])[0] == "", page


def test_titles_are_tidied_for_reading():
    assert sc.tidy_title("XIX.- DUNKIRK, GHENT, AND BRUGES") == "XIX. Dunkirk, Ghent, and Bruges"
    assert sc.tidy_title("XXL— LILLE") == "XXI. Lille"
    assert sc.tidy_title("APPENDIX II SLANDER") == "Appendix II. Slander"
    assert sc.tidy_title("XXIV.— THE MISERY OF FRANCE") == "XXIV. The Misery of France"
    assert sc.tidy_title("EPILOGUE AN ESSAY ON MILITARISM") == "Epilogue. An Essay on Militarism"


def test_a_chapter_number_ocr_lost_is_its_place():
    pages = [("Chapter | The Burning " + BODY, True), ("Chapter 2 Prelude " + BODY, True),
             ("Chapter & A Student Riot " + BODY, True)]
    divisions, _ = sc.rebuild(pages)
    assert [t for t, _ in divisions] == ["Chapter 1", "Chapter 2", "Chapter 3"]


def test_a_table_of_figures_is_not_read_aloud():
    pages = [("Chapter 1 " + BODY, True),
             ("Appendix A CENSUS 1958 2773 75.9 1959 2801 76.4 1960 2950 77.0 1961 3012", True)]
    divisions, report = sc.rebuild(pages)
    assert [t for t, _ in divisions] == ["Chapter 1"]
    assert report.apparatus


# --------------------------------------------------------------------------- #
# Footnotes
# --------------------------------------------------------------------------- #
def test_footnotes_come_off_the_foot_of_the_page():
    page = (f"{BODY}. The former expedient they regarded as \" humiliating,\" and the "
            "latter as \" subject to great risks. \"^ * Coxe, vol. ii., p. 69. "
            "2 Mimoires de Goslinga, p. 31.")
    text, notes = sc.split_notes(page)
    assert text.endswith("great risks. \"^") and len(notes) == 2


def test_a_footnote_after_a_sentence_broken_overleaf():
    page = f"{BODY} and nothing could be more for the advantage of 1- Murray, vol. iii., p. 360."
    assert sc.split_notes(page)[0].endswith("advantage of")
    glued = f"{BODY}, and also with the governors of Aude1 Hare MSS.: July 26, 1708."
    assert sc.split_notes(glued)[0].endswith("governors of Aude")


def test_ibid_however_ocr_spells_it():
    page = f"{BODY} upon Marlborough himself. 1 Ibid., p. 70: Marlborough to Godolphin. 2 J^id."
    assert sc.split_notes(page)[0].endswith("himself.")


def test_the_last_sentence_of_a_page_is_not_a_footnote():
    page = f"{BODY}. 2 Regiments were sent forward to hold the bridge before night fell."
    assert sc.split_notes(page) == (page, [])


def test_footnote_markers_leave_the_running_text():
    assert sc.drop_markers('with reason be attacked."^ Nevertheless') == \
        'with reason be attacked." Nevertheless'


# --------------------------------------------------------------------------- #
# Words
# --------------------------------------------------------------------------- #
def test_pages_join_where_a_word_breaks_across_them():
    assert sc.join_pages(["the operations were co-", "ordinated by Cadogan"]) == \
        "the operations were coordinated by Cadogan"


def test_words_split_by_a_lost_hyphen_are_rejoined_from_the_book_itself():
    # As in a real book: "in" and "to" are everywhere, "into" less so.
    common = " ".join(["in the field", "to the river"] * 30)
    text = ("Louvain fell. Brussels and Louvain were open towns. Lou vain was taken. "
            "He came in to the room, and went into the hall, into the garden. " + common)
    fixed = sc.mend_words(text)
    assert "Louvain was taken" in fixed
    assert "came in to the room" in fixed          # both halves are common words


def test_letter_confusions_are_mended_from_the_books_own_spelling():
    text = " ".join(["which"] * 12 + ["wliich"] + ["allies"] * 8 + ["alHes"] * 2)
    fixed = sc.mend_words(text)
    assert "wliich" not in fixed and "alHes" not in fixed


# --------------------------------------------------------------------------- #
# The quality verdict
# --------------------------------------------------------------------------- #
def test_a_scan_is_judged_by_its_share_of_unreadable_pages():
    """The Archive notes accuracy only on pages it could not read. Averaging
    11 bookplates and maps called a readable 578-page book "10% accurate"."""
    r = epub_reader.EpubReport(path="x.epub", documents=578, characters=1_300_000,
                               ocr_pages=11, page_scan=True)
    epub_reader._add_warnings(r)
    assert r.usable
    assert any("11 of 578 pages" in w for w in r.warnings)


def test_a_scan_that_is_mostly_unreadable_is_still_called_so():
    r = epub_reader.EpubReport(path="x.epub", documents=100, characters=90_000,
                               ocr_pages=90, ocr_accuracy=24.0)
    epub_reader._add_warnings(r)
    assert not r.usable


def test_ocr_of_a_scans_plates_does_not_replace_its_text(tmp_path, monkeypatch):
    """OCR of an EPUB reads its pictures. The Archive's Marlborough has 10 --
    maps and plates -- to 578 pages of text, and the 5,000 characters OCR got
    from them replaced the 1.3-million-character book in every build."""
    from book_creator import ocr

    book = tmp_path / "wars.epub"
    book.write_bytes(b"x")
    monkeypatch.setattr(epub_reader, "inspect", lambda p: type(
        "R", (), {"as_dict": lambda self: {"characters": 1_300_000}})())
    thin = {"path": "wars-eng-300.txt", "characters": 5_886, "modified": 2.0}
    monkeypatch.setattr(ocr, "cached_for", lambda p: [thin])
    assert ocr.best_for(book) is None
    full = dict(thin, characters=1_250_000)
    monkeypatch.setattr(ocr, "cached_for", lambda p: [full])
    assert ocr.best_for(book) == full


def test_chapter_numerals_as_ocr_sets_them():
    """Lower case, a space before the stop, and a last I read as L -- the
    chapter before says which number it must be."""
    assert sc.split_heading("v.— THE STRIFE OF PARTIES The last Parliament", [])[0] \
        == "v.— THE STRIFE OF PARTIES"
    assert sc.split_heading("XII .— SCHLANGENBERG Greeted upon every hand", [])[0] \
        == "XII .— SCHLANGENBERG"
    pages = [(f"{n}.— {t} {BODY}.", True) for n, t in
             (("VI", "1703"), ("VIL", "THE MARCH"), ("VIIL", "BAVARIA"), ("IX", "BLENHEIM"),
              ("X", "AFTER BLENHEIM"), ("XL", "THE LINES OF BRABANT"))]
    titles = [t for t, _ in sc.rebuild(pages)[0]]
    assert [t.split(".")[0] for t in titles] == ["VI", "VII", "VIII", "IX", "X", "XI"]


def test_roman_page_numbers_but_not_words_made_of_their_letters():
    assert sc.is_page_number("ix") and sc.is_page_number("xiii") and sc.is_page_number("153-")
    assert not sc.is_page_number("civil") and not sc.is_page_number("mix")
