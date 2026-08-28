# Both model modules must load together: content_pieces.avatar_id references
# content_avatars, which lives in content_generation.
from app.models import content, content_generation  # noqa: F401
