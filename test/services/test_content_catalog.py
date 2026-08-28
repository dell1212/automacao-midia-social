import os
import tempfile
import unittest

from app.services.content import catalog

_VALID_ENTRY = """
- provider: wavespeed
  kind: video
  model_id: bytedance/seedance-2.0-fast/text-to-video
  name: Seedance 2.0 Fast
  is_active: true
  supports_text_to_image: false
  supports_image_to_image: false
  supports_text_to_video: true
  supports_image_to_video: true
  supports_reference_image: true
  supports_avatar: false
  supported_ratios: ["9:16", "16:9"]
  supported_resolutions: ["720p", "1080p"]
  max_duration: 15
  cost_config:
    unit: second
    price: 0.05
    currency: USD
"""


def _write(content):
    handle = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
    handle.write(content)
    handle.close()
    return handle.name


class TestLoadCatalog(unittest.TestCase):
    def tearDown(self):
        catalog.get_catalog.cache_clear()

    def test_loads_valid_entry(self):
        path = _write(_VALID_ENTRY)
        try:
            entries = catalog.load_catalog(path)
        finally:
            os.unlink(path)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].provider, "wavespeed")
        self.assertEqual(entries[0].supported_ratios, ("9:16", "16:9"))
        self.assertEqual(entries[0].max_duration, 15)

    def test_missing_required_field_raises(self):
        path = _write(_VALID_ENTRY.replace("  model_id: bytedance", "  other: bytedance"))
        try:
            with self.assertRaises(catalog.ModelCatalogError):
                catalog.load_catalog(path)
        finally:
            os.unlink(path)

    def test_duplicate_model_id_for_same_provider_raises(self):
        path = _write(_VALID_ENTRY + _VALID_ENTRY)
        try:
            with self.assertRaises(catalog.ModelCatalogError):
                catalog.load_catalog(path)
        finally:
            os.unlink(path)

    def test_unknown_kind_raises(self):
        path = _write(_VALID_ENTRY.replace("kind: video", "kind: hologram"))
        try:
            with self.assertRaises(catalog.ModelCatalogError):
                catalog.load_catalog(path)
        finally:
            os.unlink(path)

    def test_non_list_root_raises(self):
        path = _write("provider: wavespeed\n")
        try:
            with self.assertRaises(catalog.ModelCatalogError):
                catalog.load_catalog(path)
        finally:
            os.unlink(path)


class TestListModels(unittest.TestCase):
    def tearDown(self):
        catalog.get_catalog.cache_clear()

    def test_bundled_catalog_loads_and_filters(self):
        video_models = catalog.list_models(kind="video")
        voice_models = catalog.list_models(kind="voice")

        self.assertTrue(video_models)
        self.assertTrue(voice_models)
        self.assertTrue(all(m.kind == "video" for m in video_models))
        self.assertTrue(all(m.kind == "voice" for m in voice_models))

    def test_filters_by_provider(self):
        models = catalog.list_models(provider="elevenlabs")

        self.assertTrue(models)
        self.assertTrue(all(m.provider == "elevenlabs" for m in models))


if __name__ == "__main__":
    unittest.main()
