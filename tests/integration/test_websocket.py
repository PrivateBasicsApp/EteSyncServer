"""Websocket sessions against a fake Redis: every session releases its pub/sub connection when it ends."""

import asyncio

import pytest
from fastapi import status

from etebase_server.django import models

from .helpers import create_collection, new_uid
from .websocket_helpers import WebSocketSession, eventually, fake_redis


@pytest.fixture
def col_uid(api_request, auth_token):
    uid = new_uid()
    assert create_collection(api_request, auth_token, uid)[0] == 201
    return uid


def add_member(col_uid, user):
    return models.CollectionMember.objects.create(
        collection=models.Collection.objects.get(uid=col_uid),
        user=user,
        accessLevel=models.AccessLevels.READ_ONLY,
        encryptionKey=b"encryption-key",
    )


async def get_ticket(async_api_request, token, col_uid):
    status_code, body = await async_api_request(
        "POST", f"/api/v1/collection/{col_uid}/item/subscription-ticket/", token=token
    )
    assert status_code == 200
    return body["ticket"]


async def subscribe(app, async_api_request, token, col_uid):
    """Open a session and consume the catch-up message with the items already in the collection."""
    session = WebSocketSession(app, f"/api/v1/ws/{await get_ticket(async_api_request, token, col_uid)}/")
    await session.next_message()
    return session


def test_ended_session_releases_its_subscription(app, async_api_request, auth_token, col_uid):
    async def scenario():
        async with fake_redis() as redis:
            session = await subscribe(app, async_api_request, auth_token, col_uid)

            await session.disconnect()

            await eventually(lambda: redis.subscriber_count() == 0)

    asyncio.run(scenario())


def test_refused_session_releases_its_subscription(app, async_api_request, other_user, other_auth_token, col_uid):
    membership = add_member(col_uid, other_user)

    async def scenario():
        async with fake_redis() as redis:
            ticket = await get_ticket(async_api_request, other_auth_token, col_uid)
            await asyncio.to_thread(membership.delete)
            session = WebSocketSession(app, f"/api/v1/ws/{ticket}/")

            await session.wait_finished()

            assert session.close_code == status.WS_1008_POLICY_VIOLATION
            await eventually(lambda: redis.subscriber_count() == 0)

    asyncio.run(scenario())
