from __future__ import annotations

import unittest
from unittest.mock import patch

from kokorotts.catalog import (
    CUSTOM_VOICE_ASSETS,
    VIETNAMESE_MODEL_FAMILY,
    VIETNAMESE_REPO_ID,
    VIETNAMESE_VOICE_FILES,
    voice_language,
    voices_for_language,
)
from kokorotts.pipeline import KPipeline
from kokorotts.prefetch_assets import main as prefetch_assets


class VietnameseSupportTest(unittest.TestCase):
    def test_catalog_maps_all_upstream_voices_to_one_model_family(self) -> None:
        self.assertEqual(voices_for_language("v"), list(VIETNAMESE_VOICE_FILES))
        for voice_id, voice_file in VIETNAMESE_VOICE_FILES.items():
            asset = CUSTOM_VOICE_ASSETS[voice_id]
            self.assertEqual(voice_language(voice_id), "v")
            self.assertEqual(asset["model_family"], VIETNAMESE_MODEL_FAMILY)
            self.assertEqual(asset["repo_id"], VIETNAMESE_REPO_ID)
            self.assertEqual(asset["model_file"], "kokoro_vi.pth")
            self.assertEqual(asset["config_file"], "config.json")
            self.assertEqual(asset["voice_file"], voice_file)

    def test_vig2p_phonemizes_and_normalizes_vietnamese_text(self) -> None:
        pipeline = KPipeline(lang_code="vi", model=False)
        segments = list(pipeline("Hôm nay là ngày 3 tháng 10 năm 2026."))

        self.assertEqual(len(segments), 1)
        self.assertTrue(segments[0].phonemes)
        self.assertNotIn("2026", segments[0].phonemes)

    def test_numbers_have_the_same_phonemes_as_spoken_vietnamese_words(self) -> None:
        pipeline = KPipeline(lang_code="v", model=False)
        for original, spoken in [
            ("năm 14 đời Chiêu công có Lão Kì", "năm mười bốn đời Chiêu công có Lão Kì"),
            ("14", "mười bốn"),
            ("Phần I: ĐỜI SỐNG VÀ TÁC PHẨM", "Phần một: ĐỜI SỐNG VÀ TÁC PHẨM"),
            ("Chương II: Tác phẩm", "Chương hai: Tác phẩm"),
            ("CHƯƠNG XIV", "CHƯƠNG mười bốn"),
            ("Hôm nay là năm 2026.", "Hôm nay là năm hai nghìn không trăm hai mươi sáu."),
            ("Có 21 cuốn, giá 3,14.", "Có hai mươi mốt cuốn, giá ba phẩy một bốn."),
        ]:
            for natural in (False, True):
                with self.subTest(original=original, natural=natural):
                    actual = list(pipeline(original, experimental_natural_chunking=natural))
                    expected = list(pipeline(spoken, experimental_natural_chunking=natural))
                    self.assertEqual([part.phonemes for part in actual], [part.phonemes for part in expected])
                    self.assertEqual("".join(part.graphemes for part in actual), original)

    def test_repeated_years_remain_complete_and_within_model_limits(self) -> None:
        pipeline = KPipeline(lang_code="v", model=False)
        text = "Năm 2026 có 14 cuốn sách và 25 người đọc. " * 40
        for natural in (False, True):
            segments = list(pipeline(text, experimental_natural_chunking=natural))
            self.assertGreater(len(segments), 1)
            self.assertEqual("".join(part.graphemes for part in segments).strip(), text.strip())
            self.assertTrue(all(0 < len(part.phonemes) <= 510 for part in segments))

    def test_long_vietnamese_text_is_split_without_phoneme_truncation(self) -> None:
        pipeline = KPipeline(lang_code="v", model=False)
        text = (
            "Kokoro đang kiểm tra một đoạn văn tiếng Việt dài và rõ ràng. "
            "Mọi phần của nội dung đều cần được giữ lại khi tạo âm thanh. "
        ) * 20

        segments = list(pipeline(text))

        self.assertGreater(len(segments), 1)
        self.assertTrue(all(0 < len(segment.phonemes) <= 510 for segment in segments))

    @patch("kokorotts.prefetch_assets.hf_hub_download")
    def test_prefetch_downloads_only_deployable_vietnamese_assets_once(
        self, download
    ) -> None:
        prefetch_assets()
        downloads = [
            (call.kwargs["repo_id"], call.kwargs["filename"])
            for call in download.call_args_list
        ]
        vietnamese = [item for item in downloads if item[0] == VIETNAMESE_REPO_ID]

        self.assertEqual(vietnamese.count((VIETNAMESE_REPO_ID, "kokoro_vi.pth")), 1)
        self.assertEqual(vietnamese.count((VIETNAMESE_REPO_ID, "config.json")), 1)
        self.assertEqual(
            {filename for _, filename in vietnamese if filename.startswith("voicepacks/")},
            set(VIETNAMESE_VOICE_FILES.values()),
        )
        self.assertNotIn((VIETNAMESE_REPO_ID, "kokoro_vi.onnx"), vietnamese)


if __name__ == "__main__":
    unittest.main()
