"""Tests for corp_collab.mailbox module."""

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from corp_collab.mailbox import Mailbox


@pytest.fixture
def mailbox(tmp_path: Path) -> Mailbox:
    """Create a mailbox for employee 'alice' in a temp directory."""
    db = tmp_path / "mailbox.db"
    return Mailbox("alice", db_path=db)


@pytest.fixture
def bob_mailbox(tmp_path: Path) -> Mailbox:
    """Create a mailbox for employee 'bob' sharing the same DB as alice."""
    db = tmp_path / "mailbox.db"
    return Mailbox("bob", db_path=db)


class TestSendReceiveIM:
    def test_send_and_receive_im(self, mailbox: Mailbox):
        msg_id = mailbox.send(
            channel="im",
            to_id="alice",
            to_name="Intern Alice",
            from_id="bob",
            from_name="Intern Bob",
            body="Hey Alice!",
        )
        assert isinstance(msg_id, int)
        assert msg_id > 0

        unread = mailbox.get_unread(channel="im")
        assert len(unread) == 1
        assert unread[0]["body"] == "Hey Alice!"
        assert unread[0]["channel"] == "im"
        assert unread[0]["priority"] == "urgent"  # IM is always urgent
        assert unread[0]["subject"] is None

    def test_im_ignores_subject_and_priority(self, mailbox: Mailbox):
        mailbox.send(
            channel="im",
            to_id="alice",
            to_name="Intern Alice",
            from_id="bob",
            from_name="Intern Bob",
            body="Hello",
            subject="Should be ignored",
            priority="fyi",
        )
        msg = mailbox.get_unread()[0]
        assert msg["subject"] is None
        assert msg["priority"] == "urgent"


class TestSendReceiveEmail:
    def test_send_and_receive_email(self, mailbox: Mailbox):
        msg_id = mailbox.send(
            channel="email",
            to_id="alice",
            to_name="Intern Alice",
            from_id="bob",
            from_name="Intern Bob",
            body="Please review the document.",
            subject="Document Review",
            priority="urgent",
        )
        assert msg_id > 0

        unread = mailbox.get_unread(channel="email")
        assert len(unread) == 1
        assert unread[0]["subject"] == "Document Review"
        assert unread[0]["priority"] == "urgent"
        assert unread[0]["body"] == "Please review the document."

    def test_email_default_priority(self, mailbox: Mailbox):
        mailbox.send(
            channel="email",
            to_id="alice",
            to_name="Intern Alice",
            from_id="bob",
            from_name="Intern Bob",
            body="FYI",
        )
        msg = mailbox.get_unread()[0]
        assert msg["priority"] == "normal"


class TestMarkRead:
    def test_mark_read(self, mailbox: Mailbox):
        mid1 = mailbox.send("im", "alice", "Alice", "bob", "Bob", "msg1")
        mid2 = mailbox.send("im", "alice", "Alice", "bob", "Bob", "msg2")

        assert mailbox.count_unread() == 2

        mailbox.mark_read([mid1])
        assert mailbox.count_unread() == 1

        # Verify read_at is set
        all_msgs = mailbox.get_all()
        read_msg = [m for m in all_msgs if m["id"] == mid1][0]
        assert read_msg["read"] == 1
        assert read_msg["read_at"] is not None

    def test_mark_read_empty_list(self, mailbox: Mailbox):
        mailbox.mark_read([])  # should not raise


class TestCountUnread:
    def test_count_unread(self, mailbox: Mailbox):
        assert mailbox.count_unread() == 0

        mailbox.send("im", "alice", "Alice", "bob", "Bob", "msg1")
        mailbox.send("email", "alice", "Alice", "bob", "Bob", "msg2", subject="Hi")
        assert mailbox.count_unread() == 2

    def test_count_unread_by_channel(self, mailbox: Mailbox):
        mailbox.send("im", "alice", "Alice", "bob", "Bob", "msg1")
        mailbox.send("email", "alice", "Alice", "bob", "Bob", "msg2", subject="Hi")

        assert mailbox.count_unread(channel="im") == 1
        assert mailbox.count_unread(channel="email") == 1


class TestPruneIM:
    def test_prune_keeps_last_n(self, mailbox: Mailbox):
        # Send 60 IMs from bob to alice
        for i in range(60):
            mailbox.send("im", "alice", "Alice", "bob", "Bob", f"msg {i}")

        # Should have auto-pruned to 50
        all_ims = mailbox.get_all(channel="im", limit=100)
        assert len(all_ims) == 50

        # Verify the kept messages are the most recent ones
        bodies = [m["body"] for m in all_ims]
        assert "msg 59" in bodies
        assert "msg 10" in bodies
        # msg 0-9 should be pruned
        assert "msg 0" not in bodies

    def test_prune_explicit_call(self, mailbox: Mailbox):
        for i in range(55):
            mailbox.send("im", "alice", "Alice", "bob", "Bob", f"msg {i}")

        deleted = mailbox.prune_im(keep=10)
        # After auto-prune to 50, then explicit prune to 10 = 40 deleted
        assert deleted == 40
        assert len(mailbox.get_all(channel="im", limit=100)) == 10


class TestGetUnreadFiltered:
    def test_get_unread_filtered_by_channel(self, mailbox: Mailbox):
        mailbox.send("im", "alice", "Alice", "bob", "Bob", "im msg")
        mailbox.send("email", "alice", "Alice", "bob", "Bob", "email msg", subject="Hi")

        im_unread = mailbox.get_unread(channel="im")
        email_unread = mailbox.get_unread(channel="email")
        all_unread = mailbox.get_unread()

        assert len(im_unread) == 1
        assert len(email_unread) == 1
        assert len(all_unread) == 2
        assert im_unread[0]["channel"] == "im"
        assert email_unread[0]["channel"] == "email"


class TestArchiveRead:
    def test_archive_old_read_emails(self, mailbox: Mailbox):
        # Send an email and mark it read
        mid = mailbox.send("email", "alice", "Alice", "bob", "Bob", "old email", subject="Old")
        mailbox.mark_read([mid])

        # Backdate the created_at to 48 hours ago
        old_time = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        mailbox._conn.execute(
            "UPDATE messages SET created_at = ? WHERE id = ?", (old_time, mid)
        )
        mailbox._conn.commit()

        # Send a recent email and mark it read
        mid2 = mailbox.send("email", "alice", "Alice", "bob", "Bob", "new email", subject="New")
        mailbox.mark_read([mid2])

        archived = mailbox.archive_read(older_than_hours=24)
        assert archived == 1

        # Old email should no longer appear in get_all
        all_msgs = mailbox.get_all()
        assert len(all_msgs) == 1
        assert all_msgs[0]["subject"] == "New"

    def test_archive_does_not_affect_unread(self, mailbox: Mailbox):
        mid = mailbox.send("email", "alice", "Alice", "bob", "Bob", "unread email", subject="X")
        old_time = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        mailbox._conn.execute(
            "UPDATE messages SET created_at = ? WHERE id = ?", (old_time, mid)
        )
        mailbox._conn.commit()

        archived = mailbox.archive_read(older_than_hours=24)
        assert archived == 0  # unread messages not archived

    def test_archive_does_not_affect_im(self, mailbox: Mailbox):
        mid = mailbox.send("im", "alice", "Alice", "bob", "Bob", "im msg")
        mailbox.mark_read([mid])
        old_time = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        mailbox._conn.execute(
            "UPDATE messages SET created_at = ? WHERE id = ?", (old_time, mid)
        )
        mailbox._conn.commit()

        archived = mailbox.archive_read(older_than_hours=24)
        assert archived == 0  # IMs not archived via this method


class TestValidation:
    def test_invalid_channel(self, mailbox: Mailbox):
        with pytest.raises(ValueError, match="Invalid channel"):
            mailbox.send("sms", "alice", "Alice", "bob", "Bob", "nope")

    def test_invalid_priority(self, mailbox: Mailbox):
        with pytest.raises(ValueError, match="Invalid priority"):
            mailbox.send("email", "alice", "Alice", "bob", "Bob", "nope", priority="critical")


class TestGetAll:
    def test_pagination(self, mailbox: Mailbox):
        for i in range(10):
            mailbox.send("email", "alice", "Alice", "bob", "Bob", f"msg {i}", subject=f"S{i}")

        page1 = mailbox.get_all(limit=5, offset=0)
        page2 = mailbox.get_all(limit=5, offset=5)
        assert len(page1) == 5
        assert len(page2) == 5
        ids_1 = {m["id"] for m in page1}
        ids_2 = {m["id"] for m in page2}
        assert ids_1.isdisjoint(ids_2)
