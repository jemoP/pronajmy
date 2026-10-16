import pytest
from django.contrib.auth.models import User
from django.test import Client


@pytest.fixture
def user(db: None) -> User:
    return User.objects.create_user("pronajmy", password="tajne-heslo-123")


@pytest.fixture
def auth_client(client: Client, user: User) -> Client:
    client.force_login(user)
    return client
