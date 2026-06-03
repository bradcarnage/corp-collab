"""Corp-Collab: Mailbox checkpoint injection between tool calls."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional


@dataclass
class CheckpointConfig:
    """Controls when/how mailbox is checked between tool calls."""

    im_check_every: int = 1  # check IMs every N tool calls (1 = every call)
    email_check_every: int = 10  # check emails every N calls
    urgent_email_always: bool = True  # always inject urgent emails regardless of interval
    max_im_inject: int = 5  # max IMs to inject at once
    max_email_inject: int = 3  # max emails to inject at once
    auto_mark_read: bool = True  # mark injected messages as read


@dataclass
class InjectedMessage:
    """A message that was injected into the agent's context."""

    id: int
    channel: str  # 'im' or 'email'
    from_name: str
    body: str
    subject: Optional[str] = None
    priority: str = "normal"


@dataclass
class CheckpointResult:
    """Result of a checkpoint check."""

    tool_call_count: int
    messages_injected: list[InjectedMessage] = field(default_factory=list)
    has_steers: bool = False  # True if any IM was a steer/redirect

    @property
    def has_messages(self) -> bool:
        return len(self.messages_injected) > 0

    def format_injection(self) -> str:
        """Format messages for injection into agent context."""
        if not self.messages_injected:
            return ""
        lines = ["\n--- INCOMING MESSAGES ---"]
        for msg in self.messages_injected:
            if msg.priority == "urgent":
                prefix = "🔴 "
            elif msg.channel == "email":
                prefix = "📨 "
            else:
                prefix = "💬 "
            header = f"{prefix}[{msg.channel.upper()}] From {msg.from_name}"
            if msg.subject:
                header += f" | Subject: {msg.subject}"
            lines.append(header)
            lines.append(f"  {msg.body}")
            lines.append("")
        lines.append("--- END MESSAGES ---\n")
        return "\n".join(lines)


_STEER_KEYWORDS = ("stop", "redirect", "switch to", "abort", "pause", "steer")


class CheckpointMonitor:
    """Monitors an employee's mailbox and injects messages at tool-call boundaries."""

    def __init__(
        self,
        employee_id: str,
        config: CheckpointConfig | None = None,
        base_path: Path | None = None,
    ):
        self.employee_id = employee_id
        self.config = config or CheckpointConfig()
        self.base_path = base_path or Path.home() / ".claude-code" / "collab"
        self._tool_call_count = 0
        self._total_injected = 0
        self._steer_callbacks: list[Callable] = []

    def on_steer(self, callback: Callable[[InjectedMessage], None]) -> None:
        """Register callback for steer/redirect IMs."""
        self._steer_callbacks.append(callback)

    def check(self) -> CheckpointResult:
        """Check mailbox. Call this between tool calls.

        Returns CheckpointResult with any messages to inject.
        """
        self._tool_call_count += 1
        result = CheckpointResult(tool_call_count=self._tool_call_count)

        from corp_collab.mailbox import Mailbox

        db_path = self.base_path / "employees" / self.employee_id / "mailbox.db"
        mailbox = Mailbox(self.employee_id, db_path=db_path)

        try:
            # Always check IMs at configured interval
            if self._tool_call_count % self.config.im_check_every == 0:
                ims = mailbox.get_unread(channel="im")
                for msg in ims[: self.config.max_im_inject]:
                    injected = InjectedMessage(
                        id=msg["id"],
                        channel="im",
                        from_name=msg["from_name"],
                        body=msg["body"],
                        priority=msg.get("priority", "normal"),
                    )
                    # Detect steers
                    if any(kw in msg["body"].lower() for kw in _STEER_KEYWORDS):
                        result.has_steers = True
                        for cb in self._steer_callbacks:
                            cb(injected)
                    result.messages_injected.append(injected)

            # Check emails at configured interval OR if urgent
            check_email = self._tool_call_count % self.config.email_check_every == 0
            if check_email or self.config.urgent_email_always:
                emails = mailbox.get_unread(channel="email")
                if not check_email:
                    # Only urgent emails outside normal interval
                    emails = [e for e in emails if e.get("priority") == "urgent"]
                for msg in emails[: self.config.max_email_inject]:
                    injected = InjectedMessage(
                        id=msg["id"],
                        channel="email",
                        from_name=msg["from_name"],
                        body=msg["body"],
                        subject=msg.get("subject"),
                        priority=msg.get("priority", "normal"),
                    )
                    result.messages_injected.append(injected)

            # Mark injected messages as read
            if self.config.auto_mark_read and result.messages_injected:
                ids = [m.id for m in result.messages_injected]
                mailbox.mark_read(ids)

            self._total_injected += len(result.messages_injected)
        finally:
            mailbox.close()

        return result

    @property
    def tool_call_count(self) -> int:
        return self._tool_call_count

    @property
    def total_injected(self) -> int:
        return self._total_injected

    def reset_count(self) -> None:
        """Reset tool call counter (e.g. at burst start)."""
        self._tool_call_count = 0
