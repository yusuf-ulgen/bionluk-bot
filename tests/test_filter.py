import pytest
from src.filter_engine import FilterEngine, turkish_lower


def test_turkish_lower_characters():
    assert turkish_lower("İSTANBUL") == "istanbul"
    assert turkish_lower("IŞIK") == "ışık"
    assert turkish_lower("ÇÖP") == "çöp"
    assert turkish_lower("AĞAÇ") == "ağaç"
    assert turkish_lower("ÜZÜM") == "üzüm"


def test_empty_include_allows_all_non_excluded():
    engine = FilterEngine(included_keywords=[], excluded_keywords=["ödev"])
    
    res1 = engine.evaluate("Python botu yazdırmak istiyorum", "Detaylar burada")
    assert res1.is_match is True

    res2 = engine.evaluate("Ödev teslimi yapılacak", "")
    assert res2.is_match is False
    assert "ödev" in res2.matched_exclude.lower()


def test_include_keywords_match_any():
    engine = FilterEngine(
        included_keywords=["python", "flutter", "react native"],
        excluded_keywords=[]
    )
    
    # Eşleşen
    res = engine.evaluate("Bana acil Python ile bot lazım")
    assert res.is_match is True
    assert res.matched_include == "python"

    # Eşleşmeyen
    res_none = engine.evaluate("Wordpress sitesi kurulacak")
    assert res_none.is_match is False


def test_exclude_has_priority_over_include():
    engine = FilterEngine(
        included_keywords=["python"],
        excluded_keywords=["stajyer", "ücretsiz"]
    )
    
    # Hem python hem stajyer içeriyor
    res = engine.evaluate("Python stajyer aranıyor", "Öğrenci aranıyor")
    assert res.is_match is False
    assert "stajyer" in res.matched_exclude.lower()


def test_multi_word_phrases():
    engine = FilterEngine(
        included_keywords=["web tasarımı", "yapay zeka"],
        excluded_keywords=["hazır şablon"]
    )
    
    res = engine.evaluate("Kurumsal Web Tasarımı Yaptırılacaktır", "Modern arayüz")
    assert res.is_match is True
    assert res.matched_include == "web tasarımı"

    res_exc = engine.evaluate("Web Tasarımı Hazır Şablon ile yapılacak")
    assert res_exc.is_match is False


def test_search_in_description_when_title_has_no_match():
    engine = FilterEngine(included_keywords=["fastapi"], excluded_keywords=[])
    res = engine.evaluate(
        title="Backend API geliştiricisi aranıyor",
        description="Projede FastAPI ve PostgreSQL kullanılacaktır."
    )
    assert res.is_match is True
    assert res.matched_include == "fastapi"
