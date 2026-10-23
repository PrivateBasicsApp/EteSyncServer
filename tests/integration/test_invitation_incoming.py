"""Accepting an invitation that conflicts with existing data is rejected instead of failing with a 500."""

import secrets

import pytest

from etebase_server.django import models

from .helpers import create_collection, new_uid


@pytest.fixture
def invitation_uid(api_request, auth_token, other_user):
    """An invitation from ``user`` to ``other_user`` for a new collection of ``user``."""
    col_uid = new_uid()
    assert create_collection(api_request, auth_token, col_uid)[0] == 201
    uid = new_uid()
    body = {
        "uid": uid,
        "version": 1,
        "accessLevel": models.AccessLevels.READ_ONLY,
        "username": other_user.username,
        "collection": col_uid,
        "signedEncryptionKey": b"signed-encryption-key",
    }
    assert api_request("POST", "/api/v1/invitation/outgoing/", body=body, token=auth_token)[0] == 201
    return uid


def accept(api_request, token, invitation_uid, collection_type):
    body = {"collectionType": collection_type, "encryptionKey": b"encryption-key"}
    return api_request("POST", f"/api/v1/invitation/incoming/{invitation_uid}/accept/", body=body, token=token)


def test_accepting_when_already_a_member_is_a_conflict(api_request, other_user, other_auth_token, invitation_uid):
    models.CollectionMember.objects.create(
        collection=models.CollectionInvitation.objects.get(uid=invitation_uid).collection,
        user=other_user,
        accessLevel=models.AccessLevels.READ_ONLY,
        encryptionKey=b"encryption-key",
    )

    status, body = accept(api_request, other_auth_token, invitation_uid, secrets.token_bytes(16))

    assert status == 409
    assert body["code"] == "member_exists"
    assert models.CollectionInvitation.objects.filter(uid=invitation_uid).exists()


def test_accepting_with_the_collection_type_of_another_user_is_rejected(
    api_request, user, other_user, other_auth_token, invitation_uid
):
    collection_type_of_user = bytes(models.CollectionType.objects.get(owner=user).uid)

    status, body = accept(api_request, other_auth_token, invitation_uid, collection_type_of_user)

    assert status == 400
    assert body["code"] == "bad_collection_type"
    assert not models.CollectionMember.objects.filter(user=other_user).exists()
    assert models.CollectionInvitation.objects.filter(uid=invitation_uid).exists()
