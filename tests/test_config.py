import pytest
from pydantic import ValidationError

from app.config import Settings


def test_production_rejects_demo_secrets():
    with pytest.raises(ValidationError, match="insecure production defaults"):
        Settings(app_env="production")
