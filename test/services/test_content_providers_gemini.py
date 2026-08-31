import base64
import unittest
from unittest.mock import MagicMock, patch

from app.services.content.errors import GenerationError, GenerationErrorCode
from app.services.content.providers import gemini


def _response(status_code=200, json_data=None):
    response = MagicMock(status_code=status_code)
    response.json.return_value = json_data or {}
    return response


def _source_image_response():
    return MagicMock(
        status_code=200,
        content=b"FAKEPNGBYTES",
        headers={"Content-Type": "image/png"},
    )


class TestGenerateImage(unittest.TestCase):
    def test_without_source_image_sends_only_the_text_part(self):
        response = _response(
            json_data={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "inlineData": {
                                        "data": base64.b64encode(b"OUT").decode(),
                                        "mimeType": "image/png",
                                    }
                                }
                            ]
                        }
                    }
                ]
            }
        )

        with patch.object(gemini.requests, "post", return_value=response) as post:
            gemini.generate_image(api_key="k", model_id="m", prompt="a cat")

        parts = post.call_args.kwargs["json"]["contents"][0]["parts"]
        self.assertEqual(parts, [{"text": "a cat"}])

    def test_with_source_image_downloads_and_embeds_it_before_the_prompt(self):
        response = _response(
            json_data={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "inlineData": {
                                        "data": base64.b64encode(b"OUT").decode(),
                                        "mimeType": "image/png",
                                    }
                                }
                            ]
                        }
                    }
                ]
            }
        )

        with patch.object(
            gemini.requests, "get", return_value=_source_image_response()
        ), patch.object(gemini.requests, "post", return_value=response) as post:
            gemini.generate_image(
                api_key="k",
                model_id="m",
                prompt="edit this",
                source_image_url="https://supabase.example/x.png",
            )

        parts = post.call_args.kwargs["json"]["contents"][0]["parts"]
        self.assertEqual(
            parts[0],
            {
                "inlineData": {
                    "mimeType": "image/png",
                    "data": base64.b64encode(b"FAKEPNGBYTES").decode("ascii"),
                }
            },
        )
        self.assertEqual(parts[1], {"text": "edit this"})

    def test_returns_the_decoded_image_bytes(self):
        response = _response(
            json_data={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "inlineData": {
                                        "data": base64.b64encode(b"IMAGEBYTES").decode(),
                                        "mimeType": "image/jpeg",
                                    }
                                }
                            ]
                        }
                    }
                ]
            }
        )

        with patch.object(gemini.requests, "post", return_value=response):
            asset = gemini.generate_image(api_key="k", model_id="m", prompt="a cat")

        self.assertEqual(asset.data, b"IMAGEBYTES")
        self.assertEqual(asset.mime_type, "image/jpeg")

    def test_safety_refusal_raises_content_policy(self):
        response = _response(
            json_data={"candidates": [{"finishReason": "SAFETY", "content": {"parts": []}}]}
        )

        with patch.object(gemini.requests, "post", return_value=response):
            with self.assertRaises(GenerationError) as ctx:
                gemini.generate_image(api_key="k", model_id="m", prompt="a cat")

        self.assertEqual(ctx.exception.code, GenerationErrorCode.content_policy)

    def test_no_image_data_raises_unknown(self):
        response = _response(json_data={"candidates": []})

        with patch.object(gemini.requests, "post", return_value=response):
            with self.assertRaises(GenerationError) as ctx:
                gemini.generate_image(api_key="k", model_id="m", prompt="a cat")

        self.assertEqual(ctx.exception.code, GenerationErrorCode.unknown)

    def test_source_image_download_failure_is_wrapped(self):
        with patch.object(gemini.requests, "get", side_effect=gemini.requests.ConnectionError("boom")):
            with self.assertRaises(GenerationError) as ctx:
                gemini.generate_image(
                    api_key="k",
                    model_id="m",
                    prompt="edit this",
                    source_image_url="https://supabase.example/x.png",
                )

        self.assertEqual(ctx.exception.code, GenerationErrorCode.transient)


class TestGenerateVideo(unittest.TestCase):
    def _done_operation_response(self, encoded=b"VIDEOBYTES"):
        return _response(
            json_data={
                "done": True,
                "response": {
                    "generateVideoResponse": {
                        "generatedSamples": [
                            {"video": {"bytesBase64Encoded": base64.b64encode(encoded).decode()}}
                        ]
                    }
                },
            }
        )

    def test_without_source_image_omits_the_image_field(self):
        submit = _response(json_data={"name": "operations/abc"})
        poll = self._done_operation_response()

        with patch.object(gemini.requests, "post", return_value=submit) as post, patch.object(
            gemini.requests, "get", return_value=poll
        ):
            gemini.generate_video(api_key="k", model_id="m", prompt="animate")

        instance = post.call_args.kwargs["json"]["instances"][0]
        self.assertNotIn("image", instance)

    def test_with_source_image_sends_bytes_base64_encoded_not_gcs_uri(self):
        submit = _response(json_data={"name": "operations/abc"})
        poll = self._done_operation_response()

        with patch.object(gemini.requests, "post", return_value=submit) as post, patch.object(
            gemini.requests, "get", side_effect=[_source_image_response(), poll]
        ):
            gemini.generate_video(
                api_key="k",
                model_id="m",
                prompt="animate",
                source_image_url="https://supabase.example/x.png",
            )

        instance = post.call_args.kwargs["json"]["instances"][0]
        self.assertNotIn("gcsUri", instance["image"])
        self.assertEqual(
            instance["image"],
            {
                "bytesBase64Encoded": base64.b64encode(b"FAKEPNGBYTES").decode("ascii"),
                "mimeType": "image/png",
            },
        )

    def test_returns_decoded_video_bytes_once_done(self):
        submit = _response(json_data={"name": "operations/abc"})
        poll = self._done_operation_response(encoded=b"FINALVIDEO")

        with patch.object(gemini.requests, "post", return_value=submit), patch.object(
            gemini.requests, "get", return_value=poll
        ):
            asset = gemini.generate_video(api_key="k", model_id="m", prompt="animate")

        self.assertEqual(asset.data, b"FINALVIDEO")
        self.assertEqual(asset.mime_type, "video/mp4")

    def test_missing_operation_name_raises_unknown(self):
        submit = _response(json_data={})

        with patch.object(gemini.requests, "post", return_value=submit):
            with self.assertRaises(GenerationError) as ctx:
                gemini.generate_video(api_key="k", model_id="m", prompt="animate")

        self.assertEqual(ctx.exception.code, GenerationErrorCode.unknown)

    def test_operation_error_raises_unknown(self):
        submit = _response(json_data={"name": "operations/abc"})
        poll = _response(json_data={"done": True, "error": {"code": 13}})

        with patch.object(gemini.requests, "post", return_value=submit), patch.object(
            gemini.requests, "get", return_value=poll
        ):
            with self.assertRaises(GenerationError) as ctx:
                gemini.generate_video(api_key="k", model_id="m", prompt="animate")

        self.assertEqual(ctx.exception.code, GenerationErrorCode.unknown)

    def test_operation_policy_error_raises_content_policy(self):
        submit = _response(json_data={"name": "operations/abc"})
        poll = _response(
            json_data={
                "done": True,
                "error": {"code": 3, "message": "Request violates content policy"},
            }
        )

        with patch.object(gemini.requests, "post", return_value=submit), patch.object(
            gemini.requests, "get", return_value=poll
        ):
            with self.assertRaises(GenerationError) as ctx:
                gemini.generate_video(api_key="k", model_id="m", prompt="animate")

        self.assertEqual(ctx.exception.code, GenerationErrorCode.content_policy)

    def test_deadline_elapsed_raises_timeout_without_polling(self):
        submit = _response(json_data={"name": "operations/abc"})

        with patch.object(gemini.requests, "post", return_value=submit), patch.object(
            gemini.requests, "get"
        ) as get, patch.object(gemini.time, "monotonic", side_effect=[0, 100]):
            with self.assertRaises(GenerationError) as ctx:
                gemini.generate_video(
                    api_key="k", model_id="m", prompt="animate", poll_timeout=10
                )

        self.assertEqual(ctx.exception.code, GenerationErrorCode.timeout)
        get.assert_not_called()


class TestValidateCredentials(unittest.TestCase):
    def test_accepted_key_does_not_raise(self):
        with patch.object(gemini.requests, "get", return_value=_response(200)):
            gemini.validate_credentials("k")

    def test_rejected_key_raises_invalid_credentials(self):
        with patch.object(gemini.requests, "get", return_value=_response(401)):
            with self.assertRaises(GenerationError) as ctx:
                gemini.validate_credentials("bad-key")

        self.assertEqual(ctx.exception.code, GenerationErrorCode.invalid_credentials)


if __name__ == "__main__":
    unittest.main()
