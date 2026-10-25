"""
İlan başlığı ve açıklamasını Türkçe kurallarına uygun şekilde filtreleyen motor.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple


def turkish_lower(text: str) -> str:
    """Türkçe karakterleri (İ, I, Ş, vb.) küçük harfe çevirir."""
    if not text:
        return ""
    mapping = {
        "İ": "i",
        "I": "ı",
        "Ç": "ç",
        "Ş": "ş",
        "Ö": "ö",
        "Ü": "ü",
        "Ğ": "ğ",
    }
    chars = [mapping.get(ch, ch.lower()) for ch in text]
    return "".join(chars)


def to_search_folded(text: str) -> str:
    """
    Arama için Türkçe karakterleri de ASCII eşdeğerlerine katlar (case and diacritics folding).
    Böylece 'FastAPI' ile 'fastapi', 'tasarım' ile 'tasarim' birbirini kaçırmaz.
    """
    t = turkish_lower(text)
    trans = str.maketrans({
        "ı": "i",
        "ğ": "g",
        "ü": "u",
        "ş": "s",
        "ö": "o",
        "ç": "c",
    })
    return t.translate(trans)


def normalize_spaces(text: str) -> str:
    """Fazlalık boşlukları temizler ve teke indirir."""
    return re.sub(r"\s+", " ", text).strip()


@dataclass
class FilterResult:
    is_match: bool
    matched_include: Optional[str] = None
    matched_exclude: Optional[str] = None
    reason: str = ""


class FilterEngine:
    def __init__(self, included_keywords: List[str] | None = None, excluded_keywords: List[str] | None = None):
        self.included_keywords: List[str] = included_keywords or []
        self.excluded_keywords: List[str] = excluded_keywords or []

    def update_rules(self, included: List[str], excluded: List[str]):
        """Filtre kurallarını çalışma anında günceller."""
        self.included_keywords = [normalize_spaces(k) for k in included if normalize_spaces(k)]
        self.excluded_keywords = [normalize_spaces(k) for k in excluded if normalize_spaces(k)]

    def evaluate(self, title: str, description: str = "") -> FilterResult:
        """
        Bir ilanın başlık ve açıklamasını mevcut kurallara göre değerlendirir.
        Kural Sıralaması:
        1. Hariç tutulan (exclude) kelimeler önceliklidir. Herhangi biri varsa ilan elenir.
        2. Dahil edilen (include) listesi boşsa ve hariç kelime yoksa ilan kabul edilir.
        3. Dahil edilen listesi doluysa, en az birinin eşleşmesi şarttır.
        """
        raw_combined = normalize_spaces(f"{title} {description}")
        text_tr = turkish_lower(raw_combined)
        text_folded = to_search_folded(raw_combined)

        # 1. Hariç kelimeleri kontrol et
        for exc in self.excluded_keywords:
            exc_clean = normalize_spaces(exc)
            if not exc_clean:
                continue
            if self._contains_keyword(text_tr, text_folded, exc_clean):
                return FilterResult(
                    is_match=False,
                    matched_exclude=exc,
                    reason=f"Hariç tutulan kelime eşleşti: '{exc}'"
                )

        # 2. Dahil edilen kelimeler boşsa -> direkt kabul
        if not self.included_keywords:
            return FilterResult(
                is_match=True,
                reason="Dahil kelimesi belirtilmediği için tüm ilanlar kabul edildi."
            )

        # 3. Dahil edilen kelimelerden en az biri eşleşmeli
        for inc in self.included_keywords:
            inc_clean = normalize_spaces(inc)
            if not inc_clean:
                continue
            if self._contains_keyword(text_tr, text_folded, inc_clean):
                return FilterResult(
                    is_match=True,
                    matched_include=inc,
                    reason=f"Dahil kelimesi eşleşti: '{inc}'"
                )

        return FilterResult(
            is_match=False,
            reason="Dahil edilen kelimelerin hiçbiriyle eşleşmedi."
        )

    def _contains_keyword(self, target_tr: str, target_folded: str, keyword: str) -> bool:
        """
        Kelimenin doğrudan Türkçe veya ASCII katlanmış haliyle metinde bulunup bulunmadığını kontrol eder.
        """
        kw_tr = turkish_lower(keyword)
        if kw_tr in target_tr:
            return True
        kw_folded = to_search_folded(keyword)
        return kw_folded in target_folded
