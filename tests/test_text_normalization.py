from __future__ import annotations

import unittest

from kokorotts.catalog import DEFAULT_MODEL_REPO_ID
from kokorotts.pipeline import KPipeline
from kokorotts.text_normalization import (
    expand_english_eras,
    expand_english_large_units,
    expand_english_measurements,
    expand_english_roman_numerals,
    normalize_english_text,
    normalize_vietnamese_text,
    strip_english_markdown_emphasis,
)


class RecordingG2P:
    def __init__(self) -> None:
        self.inputs: list[str] = []

    def __call__(self, text: str):
        self.inputs.append(text)
        return text, []


class EnglishLargeUnitNormalizationTest(unittest.TestCase):
    def test_expands_supported_units(self) -> None:
        self.assertEqual(
            expand_english_large_units("20K, 3M, 4B, and 5T"),
            "20 thousand, 3 million, 4 billion, and 5 trillion",
        )

    def test_preserves_currency_and_decimal_values(self) -> None:
        self.assertEqual(
            expand_english_large_units("$1.5M, £2B, and $1,200K"),
            "$1.5 million, £2 billion, and $1,200 thousand",
        )

    def test_ignores_ambiguous_or_identifier_suffixes(self) -> None:
        text = "10m, 64MB, ABC12M, v2B, and 3_k"
        self.assertEqual(expand_english_large_units(text), text)

    def test_english_pipeline_normalizes_before_g2p(self) -> None:
        pipeline = KPipeline.__new__(KPipeline)
        pipeline.lang_code = "a"
        pipeline.model = None
        pipeline.g2p = RecordingG2P()

        self.assertEqual(list(pipeline("The file has 20K rows.", model=False)), [])
        self.assertEqual(pipeline.g2p.inputs, ["The file has 20 thousand rows."])

    def test_non_english_pipeline_does_not_apply_english_expansion(self) -> None:
        pipeline = KPipeline.__new__(KPipeline)
        pipeline.lang_code = "f"
        pipeline.model = None
        pipeline.g2p = RecordingG2P()

        results = list(pipeline("Le fichier contient 20K lignes.", model=False))

        self.assertEqual(pipeline.g2p.inputs, ["Le fichier contient 20K lignes."])
        self.assertEqual(results[0].phonemes, "Le fichier contient 20K lignes.")


class EnglishIssue108NormalizationTest(unittest.TestCase):
    def test_expands_issue_measurements_with_correct_pluralization(self) -> None:
        self.assertEqual(
            expand_english_measurements("1m, 10 m, 32ft, 40cm, 1 in, 1.5km"),
            "1 meter, 10 meters, 32 feet, 40 centimeters, 1 inch, 1.5 kilometers",
        )

    def test_measurements_preserve_identifiers_and_unrelated_units(self) -> None:
        text = "64MB, timer10m, 5ms, 10 M, 10m_value, 10m², CSS32ftRule, and room 2B"
        self.assertEqual(expand_english_measurements(text), text)

    def test_expands_year_adjacent_eras_only(self) -> None:
        self.assertEqual(
            expand_english_eras("1479 BC, 300 BCE, AD 1066, and 2026 CE"),
            "1479 before Christ, 300 before common era, anno Domini 1066, and 2026 common era",
        )
        self.assertEqual(
            expand_english_eras("BC Ferries and an AD campaign"),
            "BC Ferries and an AD campaign",
        )

    def test_expands_contextual_roman_numerals(self) -> None:
        self.assertEqual(
            expand_english_roman_numerals(
                "World War II, Chapter XI, Type II, Model IV, Thutmose II, Henry VIII, and Pope John Paul II"
            ),
            "World War 2, Chapter 11, Type 2, Model 4, Thutmose 2nd, Henry 8th, and Pope John Paul 2nd",
        )

    def test_preserves_invalid_or_context_free_capitals(self) -> None:
        text = "API IVR uses MIX tools; I agree with XML, and Chapter IIX is invalid."
        self.assertEqual(expand_english_roman_numerals(text), text)

    def test_normalizes_complete_issue_example(self) -> None:
        text = (
            "Thutmose II was an ancestor whose reign lasted from 1493 to 1479 BC. "
            "The passage had a 10m tunnel, a 32ft chamber, and a 40cm gap."
        )
        self.assertEqual(
            normalize_english_text(text),
            "Thutmose 2nd was an ancestor whose reign lasted from 1493 to 1479 before Christ. "
            "The passage had a 10 meters tunnel, a 32 feet chamber, and a 40 centimeters gap.",
        )

    def test_english_pipeline_applies_complete_normalization_before_g2p(self) -> None:
        pipeline = KPipeline.__new__(KPipeline)
        pipeline.lang_code = "a"
        pipeline.model = None
        pipeline.g2p = RecordingG2P()

        self.assertEqual(
            list(pipeline("Thutmose II crossed 10m in 1479 BC.", model=False)), []
        )
        self.assertEqual(
            pipeline.g2p.inputs,
            ["Thutmose 2nd crossed 10 meters in 1479 before Christ."],
        )

    def test_non_english_pipeline_preserves_issue_108_forms(self) -> None:
        pipeline = KPipeline.__new__(KPipeline)
        pipeline.lang_code = "f"
        pipeline.model = None
        pipeline.g2p = RecordingG2P()

        results = list(pipeline("Thutmose II, 10m, 1479 BC", model=False))

        self.assertEqual(pipeline.g2p.inputs, ["Thutmose II, 10m, 1479 BC"])
        self.assertEqual(results[0].phonemes, "Thutmose II, 10m, 1479 BC")


class EnglishIssue217NormalizationTest(unittest.TestCase):
    def test_strips_balanced_emphasis_around_contractions(self) -> None:
        self.assertEqual(
            strip_english_markdown_emphasis("You *shouldn't* and *don't* panic."),
            "You shouldn't and don't panic.",
        )

    def test_strips_single_double_and_triple_emphasis(self) -> None:
        self.assertEqual(
            strip_english_markdown_emphasis(
                "This is *important*, **very important**, and ***urgent***."
            ),
            "This is important, very important, and urgent.",
        )

    def test_preserves_literal_asterisk_uses(self) -> None:
        text = (
            "Use 2 * 3, 2*x*3, *.txt, \\*literal\\*, and * unmatched.\n"
            "* First item\n* Second item\nUse * as a symbol and * again."
        )
        self.assertEqual(strip_english_markdown_emphasis(text), text)

    def test_plain_english_pipeline_strips_emphasis_before_g2p(self) -> None:
        pipeline = KPipeline.__new__(KPipeline)
        pipeline.lang_code = "a"
        pipeline.model = None
        pipeline.g2p = RecordingG2P()

        self.assertEqual(list(pipeline("You *shouldn't* panic.", model=False)), [])
        self.assertEqual(pipeline.g2p.inputs, ["You shouldn't panic."])

    def test_explicit_ssml_pipeline_can_preserve_asterisks(self) -> None:
        pipeline = KPipeline.__new__(KPipeline)
        pipeline.lang_code = "a"
        pipeline.model = None
        pipeline.g2p = RecordingG2P()

        self.assertEqual(
            list(
                pipeline(
                    "You *shouldn't* panic.",
                    model=False,
                    normalize_markdown_emphasis=False,
                )
            ),
            [],
        )
        self.assertEqual(pipeline.g2p.inputs, ["You *shouldn't* panic."])


class EnglishPronunciationRegressionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.american = KPipeline(
            lang_code="a", repo_id=DEFAULT_MODEL_REPO_ID, model=False
        )
        cls.british = KPipeline(
            lang_code="b", repo_id=DEFAULT_MODEL_REPO_ID, model=False
        )

    @staticmethod
    def phonemes(pipeline: KPipeline, text: str) -> str:
        return "".join(result.phonemes for result in pipeline(text, model=False))

    def test_pinned_frontend_pronounces_midair_in_both_english_variants(self) -> None:
        text = "The planes collided in midair."
        american_phonemes = self.phonemes(self.american, text)
        british_phonemes = self.phonemes(self.british, text)

        self.assertIn("mˌɪdˈɛɹ", american_phonemes)
        self.assertIn("mɪdˈAə", british_phonemes)

    def test_arithmetic_uses_noun_pronunciation_outside_noun_modifiers(self) -> None:
        cases = (
            "arithmetic",
            "Basic arithmetic is useful.",
            "She teaches arithmetic.",
            "Check the arithmetic.",
        )
        for text in cases:
            with self.subTest(dialect="us", text=text):
                self.assertIn(
                    "əɹˈɪθmətˌɪk", self.phonemes(self.american, text)
                )
            with self.subTest(dialect="gb", text=text):
                self.assertIn("əɹˈɪθmətɪk", self.phonemes(self.british, text))

    def test_arithmetic_uses_adjective_pronunciation_before_nouns(self) -> None:
        cases = (
            "This arithmetic operation is simple.",
            "Calculate the arithmetic mean.",
            "The arithmetic logic unit is ready.",
        )
        for text in cases:
            with self.subTest(dialect="us", text=text):
                self.assertIn(
                    "ˌɛɹɪθmˈɛTɪk", self.phonemes(self.american, text)
                )
            with self.subTest(dialect="gb", text=text):
                self.assertIn("ˌaɹɪθmˈɛtɪk", self.phonemes(self.british, text))




class VietnameseNumberNormalizationTest(unittest.TestCase):
    def test_cardinal_numbers_and_contextual_unit_forms(self) -> None:
        cases = {
            "0": "không", "1": "một", "4": "bốn", "5": "năm",
            "10": "mười", "11": "mười một", "14": "mười bốn", "15": "mười lăm",
            "20": "hai mươi", "21": "hai mươi mốt", "24": "hai mươi bốn", "25": "hai mươi lăm",
            "101": "một trăm linh một", "105": "một trăm linh năm", "115": "một trăm mười lăm",
            "1000": "một nghìn", "1001": "một nghìn không trăm linh một",
            "1010": "một nghìn không trăm mười", "2026": "hai nghìn không trăm hai mươi sáu",
            "1000000": "một triệu", "1000001": "một triệu không trăm linh một", "1000000000": "một tỷ",
        }
        for text, spoken in cases.items():
            with self.subTest(text=text):
                self.assertEqual(normalize_vietnamese_text(text), spoken)

    def test_expands_the_reported_book_sentence_without_changing_words(self) -> None:
        self.assertEqual(
            normalize_vietnamese_text("năm 14 đời Chiêu công có Lão Kì"),
            "năm mười bốn đời Chiêu công có Lão Kì",
        )
        self.assertEqual(normalize_vietnamese_text("(14), 21; 25."), "(mười bốn), hai mươi mốt; hai mươi lăm.")

    def test_reads_part_and_chapter_roman_numbers_as_vietnamese_cardinals(self) -> None:
        for roman, spoken in {"I":"một", "II":"hai", "III":"ba", "IV":"bốn", "V":"năm", "IX":"chín", "XI":"mười một", "XIV":"mười bốn", "XXI":"hai mươi mốt", "XL":"bốn mươi"}.items():
            for label in ("Phần", "PHẦN", "phần", "Chương", "CHƯƠNG", "chương"):
                with self.subTest(roman=roman, label=label):
                    self.assertEqual(normalize_vietnamese_text(f"{label} {roman}: Nội dung"), f"{label} {spoken}: Nội dung")
        self.assertEqual(normalize_vietnamese_text("Phần I. Chương II."), "Phần một. Chương hai.")
        self.assertEqual(normalize_vietnamese_text("(Chương IV), xem Phần II."), "(Chương bốn), xem Phần hai.")

    def test_roman_normalization_preserves_other_words_and_invalid_forms(self) -> None:
        text = "I, II, CD, IVR. Phần vi mô; phần di động; chương trình; phần mềm."
        self.assertEqual(normalize_vietnamese_text(text), text)
        for text in ("Phần IIII", "Chương IIX", "Chương VX", "Phần IC", "Phần IVR", "Chương I@example.com"):
            with self.subTest(text=text):
                self.assertEqual(normalize_vietnamese_text(text), text)

    def test_grouped_numbers_and_decimal_digits(self) -> None:
        cases = {
            "1.234": "một nghìn hai trăm ba mươi bốn",
            "1.234,50": "một nghìn hai trăm ba mươi bốn phẩy năm không",
            "1,234.50": "một nghìn hai trăm ba mươi bốn phẩy năm không",
            "1,234,567": "một triệu hai trăm ba mươi bốn nghìn năm trăm sáu mươi bảy",
            "3,14": "ba phẩy một bốn", "3.14": "ba phẩy một bốn",
            "0,05": "không phẩy không năm", "0.014": "không phẩy không một bốn",
        }
        for text, spoken in cases.items():
            with self.subTest(text=text):
                self.assertEqual(normalize_vietnamese_text(text), spoken)

    def test_preserves_leading_zeroes_and_long_digit_sequences(self) -> None:
        self.assertEqual(normalize_vietnamese_text("0014"), "không không một bốn")
        self.assertEqual(normalize_vietnamese_text("1" * 30), " ".join(["một"] * 30))

    def test_signs_and_ranges_have_different_meanings(self) -> None:
        self.assertEqual(normalize_vietnamese_text("-14; −15; +21"), "âm mười bốn; âm mười lăm; cộng hai mươi mốt")
        self.assertEqual(normalize_vietnamese_text("14-21; 14–25"), "mười bốn-hai mươi mốt; mười bốn–hai mươi lăm")

    def test_does_not_rewrite_identifiers_or_interpret_invalid_numeric_formats(self) -> None:
        text = "v1.2.3, file14, id_14, 14px, 192.168.1.1 and 1.2.3"
        self.assertEqual(normalize_vietnamese_text(text), text)
        text = "https://example.com/14?year=2026 www.example.com/14 book14@example.com"
        self.assertEqual(normalize_vietnamese_text(text), text)

    def test_repeated_normalization_is_stable(self) -> None:
        text = "Năm 14, có 1.234 cuốn và giá 3,14."
        spoken = normalize_vietnamese_text(text)
        self.assertEqual(normalize_vietnamese_text(spoken), spoken)


if __name__ == "__main__":
    unittest.main()
