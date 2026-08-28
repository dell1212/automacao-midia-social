import unittest
from unittest.mock import MagicMock

from app.services.content import capability
from app.services.content.catalog import ModelEntry


def _entry(**overrides):
    base = dict(
        provider="wavespeed",
        kind="video",
        model_id="m1",
        name="M1",
        is_active=True,
        supports_text_to_image=False,
        supports_image_to_image=False,
        supports_text_to_video=True,
        supports_image_to_video=True,
        supports_reference_image=True,
        supports_avatar=False,
        supported_ratios=("9:16", "16:9"),
        supported_resolutions=("720p", "1080p"),
        max_duration=15,
        cost_config={},
    )
    base.update(overrides)
    return ModelEntry(**base)


def _requirements(**overrides):
    base = dict(
        kind="video",
        mode=capability.GenerationMode.image_to_video,
        aspect_ratio="9:16",
        resolution="1080p",
        duration=8,
        needs_reference_image=True,
    )
    base.update(overrides)
    return capability.GenerationRequirements(**base)


class TestModelSupports(unittest.TestCase):
    def test_matching_model_is_supported(self):
        self.assertTrue(capability.model_supports(_entry(), _requirements()))

    def test_wrong_kind_is_rejected(self):
        self.assertFalse(
            capability.model_supports(_entry(kind="image"), _requirements())
        )

    def test_inactive_model_is_rejected(self):
        self.assertFalse(
            capability.model_supports(_entry(is_active=False), _requirements())
        )

    def test_mode_not_supported_is_rejected(self):
        entry = _entry(supports_image_to_video=False)

        self.assertFalse(capability.model_supports(entry, _requirements()))

    def test_unsupported_ratio_is_rejected(self):
        self.assertFalse(
            capability.model_supports(_entry(), _requirements(aspect_ratio="4:5"))
        )

    def test_unsupported_resolution_is_rejected(self):
        self.assertFalse(
            capability.model_supports(_entry(), _requirements(resolution="4k"))
        )

    def test_duration_above_max_is_rejected(self):
        self.assertFalse(
            capability.model_supports(_entry(), _requirements(duration=30))
        )

    def test_duration_equal_to_max_is_accepted(self):
        self.assertTrue(
            capability.model_supports(_entry(), _requirements(duration=15))
        )

    def test_reference_image_requirement_is_enforced(self):
        entry = _entry(supports_reference_image=False)

        self.assertFalse(capability.model_supports(entry, _requirements()))

    def test_empty_constraint_lists_are_treated_as_unconstrained(self):
        entry = _entry(supported_ratios=(), supported_resolutions=(), max_duration=None)

        self.assertTrue(capability.model_supports(entry, _requirements()))

    def test_unset_requirement_does_not_constrain(self):
        requirements = _requirements(aspect_ratio=None, resolution=None, duration=None)

        self.assertTrue(capability.model_supports(_entry(), requirements))


class TestSelectCandidates(unittest.TestCase):
    def _session_with(self, providers):
        session = MagicMock()
        session.exec.return_value.all.return_value = providers
        return session

    def test_orders_by_provider_priority(self):
        low = MagicMock(id=1, provider="wavespeed", priority=10, config={})
        high = MagicMock(id=2, provider="gemini", priority=1, config={})
        session = self._session_with([low, high])

        catalog_entries = {
            "wavespeed": [_entry(provider="wavespeed", model_id="ws-1")],
            "gemini": [_entry(provider="gemini", model_id="gm-1")],
        }

        candidates = capability.select_candidates(
            session,
            tenant_id=1,
            requirements=_requirements(),
            catalog_lookup=lambda provider, kind: catalog_entries[provider],
        )

        self.assertEqual([c.model_id for c in candidates], ["gm-1", "ws-1"])

    def test_incompatible_models_are_dropped(self):
        provider_row = MagicMock(id=1, provider="wavespeed", priority=0, config={})
        session = self._session_with([provider_row])

        candidates = capability.select_candidates(
            session,
            tenant_id=1,
            requirements=_requirements(),
            catalog_lookup=lambda provider, kind: [
                _entry(model_id="bad", supports_image_to_video=False),
                _entry(model_id="good"),
            ],
        )

        self.assertEqual([c.model_id for c in candidates], ["good"])

    def test_no_providers_yields_no_candidates(self):
        session = self._session_with([])

        candidates = capability.select_candidates(
            session,
            tenant_id=1,
            requirements=_requirements(),
            catalog_lookup=lambda provider, kind: [_entry()],
        )

        self.assertEqual(candidates, [])

    def test_config_model_allowlist_filters_candidates(self):
        provider_row = MagicMock(
            id=1, provider="wavespeed", priority=0, config={"allowed_models": ["good"]}
        )
        session = self._session_with([provider_row])

        candidates = capability.select_candidates(
            session,
            tenant_id=1,
            requirements=_requirements(),
            catalog_lookup=lambda provider, kind: [
                _entry(model_id="good"),
                _entry(model_id="other"),
            ],
        )

        self.assertEqual([c.model_id for c in candidates], ["good"])


if __name__ == "__main__":
    unittest.main()
