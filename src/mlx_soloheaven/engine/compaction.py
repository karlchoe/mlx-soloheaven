"""Conversation compaction helpers."""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class CompactionStrategy(str, Enum):
    SUMMARIZE = "summarize"
    SUMMARIZE_RECENT = "summarize_recent"
    MEMORY_EXTRACT = "memory_extract"
    KEY_POINTS = "key_points"


class CompactionEngine:
    """Create lightweight summaries for long conversations."""

    def __init__(self, engine: Any):
        self.engine = engine

    @staticmethod
    def _estimate_tokens(messages: list[dict[str, Any]]) -> int:
        total_chars = 0
        for message in messages:
            content = message.get("content")
            if isinstance(content, str):
                total_chars += len(content)
            elif isinstance(content, list):
                total_chars += len(str(content))
        return max(1, total_chars // 4)

    def check_limit(self, total_tokens: int, limit: int) -> bool:
        """Return True when utilization crosses 90 percent."""
        return total_tokens >= int(limit * 0.9)

    def _build_summary_prompt(
        self,
        messages: list[dict[str, Any]],
        strategy: CompactionStrategy,
    ) -> str:
        if strategy == CompactionStrategy.MEMORY_EXTRACT:
            instruction = "Extract durable facts, preferences, constraints, and TODOs from this conversation."
        elif strategy == CompactionStrategy.KEY_POINTS:
            instruction = "Summarize the key decisions, open questions, and next steps from this conversation."
        elif strategy == CompactionStrategy.SUMMARIZE_RECENT:
            instruction = "Summarize the earlier part of this conversation and keep recent context crisp."
        else:
            instruction = "Summarize this conversation for future continuation."

        lines = [instruction, "", "Conversation:"]
        for message in messages:
            role = message.get("role", "user")
            content = message.get("content", "")
            if isinstance(content, list):
                content = str(content)
            lines.append(f"{role}: {content}")
        lines.extend(
            [
                "",
                "Return a concise summary with:",
                "- goals",
                "- important facts",
                "- decisions made",
                "- unresolved work",
            ]
        )
        return "\n".join(lines)

    async def summarize_history(
        self,
        messages: list[dict[str, Any]],
        strategy: CompactionStrategy = CompactionStrategy.SUMMARIZE,
    ) -> str:
        """Generate a summary for older conversation turns."""
        if len(messages) <= 5:
            return ""

        prompt = self._build_summary_prompt(messages, strategy)
        try:
            result = self.engine.complete(
                [{"role": "user", "content": prompt}],
                max_tokens=1024,
                temperature=0.2,
                thinking=False,
            )
        except Exception as exc:
            logger.error("Compaction failed: %s", exc)
            return "Summary unavailable."
        return (result.content or "").strip()

    async def compact(
        self,
        *,
        messages: list[dict[str, Any]],
        strategy: CompactionStrategy,
        target_tokens: int,
        keep_recent_turns: int = 10,
    ) -> dict[str, Any]:
        """Summarize older turns and estimate the reduced prompt size."""
        old_tokens = self._estimate_tokens(messages)
        if len(messages) <= keep_recent_turns:
            return {
                "summary": "",
                "new_tokens": old_tokens,
                "reduction_percent": 0.0,
                "compacted_messages": messages,
            }

        head = messages[:-keep_recent_turns]
        tail = messages[-keep_recent_turns:]
        summary = await self.summarize_history(head, strategy=strategy)
        summary_message = {
            "role": "system",
            "content": f"Conversation summary:\n{summary}" if summary else "Conversation summary unavailable.",
        }
        compacted_messages = [summary_message, *tail]
        new_tokens = min(self._estimate_tokens(compacted_messages), max(target_tokens, 1))
        reduction = max(0.0, (old_tokens - new_tokens) / max(old_tokens, 1) * 100.0)

        return {
            "summary": summary,
            "new_tokens": new_tokens,
            "reduction_percent": round(reduction, 1),
            "compacted_messages": compacted_messages,
        }
