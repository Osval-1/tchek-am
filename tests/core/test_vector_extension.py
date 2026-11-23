import pytest
from django.db import connection


@pytest.mark.django_db
def test_vector_extension_installed():
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
        assert cursor.fetchone() is not None
