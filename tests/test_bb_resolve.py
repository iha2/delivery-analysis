import pytest

from bitbucket_fakes import FakeBitbucket
from delivery_analysis.connectors.bitbucket.client import BitbucketClient
from delivery_analysis.connectors.bitbucket.resolve import resolve_repository

UUID = "{11111111-1111-1111-1111-111111111111}"


@pytest.fixture
def client():
    fake = FakeBitbucket()
    fake.add_repo("movedocs_v1.0", UUID)
    return BitbucketClient(fake.token, transport=fake.transport(), sleep=lambda s: None)


@pytest.mark.parametrize(
    "text, default",
    [
        ("keyhealthtech/movedocs_v1.0", ""),
        ("movedocs_v1.0", "keyhealthtech"),
        (UUID, "keyhealthtech"),
        ("11111111-1111-1111-1111-111111111111", "keyhealthtech"),
        ("keyhealthtech/" + UUID, ""),
    ],
)
def test_every_accepted_form_resolves_to_the_uuid(client, text, default):
    repo = resolve_repository(client, text, default)
    assert (repo.uuid, repo.workspace, repo.slug) == (UUID, "keyhealthtech", "movedocs_v1.0")


def test_a_bare_slug_without_a_workspace_is_explained(client):
    with pytest.raises(ValueError, match="BITBUCKET_WORKSPACE"):
        resolve_repository(client, "movedocs_v1.0", "")


def test_an_unknown_repository_is_a_plain_message(client):
    with pytest.raises(ValueError, match="was not found"):
        resolve_repository(client, "keyhealthtech/nope", "")
