"""
Conversation context manager — the kernel.

Maintains thread-level conversation state and builds efficient Claude API calls:
- Accumulates turns per thread (source-agnostic: Slack, email, web, API)
- Builds messages array with prompt caching (stable prefix = cached, new turn = fresh)
- Compacts old turns into summaries when context budget is exceeded
- Per-instance identity prompts and configuration

Modeled after Claude Code's context management:
- Full conversation history sent each call, but with cache_control on stable prefix
- Compaction summarizes old turns when token count crosses threshold
- Server-side context_management clears old tool results (we don't have tools,
  but we do have verbose RAG context that can be trimmed)
"""

import os
import logging
from typing import List, Dict, Optional, Tuple
from anthropic import Anthropic

from src.db.repositories.thread_repo import ThreadRepo
from src.db.repositories.instance_repo import InstanceRepo

logger = logging.getLogger(__name__)

# Token budget constants (conservative estimates, 1 token ~ 4 chars)
CHARS_PER_TOKEN = 4
MAX_CONTEXT_TOKENS = 150_000     # Stay under 200K model limit
COMPACTION_THRESHOLD = 80_000    # Compact when thread history exceeds this
COMPACTION_KEEP_TOKENS = 20_000  # Keep last ~20K tokens of turns after compaction
SUMMARY_MAX_TOKENS = 2_000       # Cap summary size


def estimate_tokens(text: str) -> int:
    """Rough token estimate. Good enough for budget tracking."""
    return len(text) // CHARS_PER_TOKEN


class ConversationManager:
    """
    Manages conversation context for a thread.

    Usage:
        mgr = ConversationManager(source_type='slack', source_ref='1234.5678',
                                  workspace_id='W123')
        system_prompt, messages = mgr.build_messages(
            new_question="What's the status of alonovo?",
            knowledge_context="[project docs and RAG results here]"
        )
        # Apply caching and call Claude
        system_blocks, cached_msgs = apply_cache_control(system_prompt, messages)
        response = client.messages.create(
            system=system_blocks, messages=cached_msgs, ...
        )
        # Store the exchange
        mgr.add_exchange(question, answer_text, metadata)
    """

    def __init__(
        self,
        source_type: str,
        source_ref: str,
        workspace_id: Optional[str] = None,
        instance_slug: Optional[str] = None,
        instance_id: Optional[int] = None
    ):
        self.source_type = source_type
        self.source_ref = source_ref
        self.workspace_id = workspace_id

        self._thread_repo = ThreadRepo()
        self._instance_repo = InstanceRepo()

        # Resolve instance
        self._instance = None
        if instance_slug:
            self._instance = self._instance_repo.get_by_slug(instance_slug)
        elif instance_id:
            self._instance = self._instance_repo.get_by_id(instance_id)

        # Get or create thread
        self._thread = self._thread_repo.get_or_create_thread(
            source_type=source_type,
            source_ref=source_ref,
            workspace_id=workspace_id,
            instance_id=self._instance['id'] if self._instance else None
        )

        # Opportunistic GC: clean up stale threads (cheap single-query DELETE)
        try:
            self._thread_repo.garbage_collect(stale_hours=24)
        except Exception:
            pass  # GC failure is non-critical

    @property
    def thread_id(self) -> int:
        return self._thread['id']

    def get_system_prompt(self) -> str:
        """
        Build system prompt for this thread's instance.
        Priority: instance DB prompt > default file prompt > hardcoded fallback.
        """
        if self._instance and self._instance.get('identity_prompt'):
            return self._instance['identity_prompt']

        from pathlib import Path
        identity_path = Path(__file__).parent.parent.parent / "prompts" / "identity.md"
        if identity_path.exists():
            return identity_path.read_text().strip()

        return (
            "You are a knowledge assistant that helps teams understand their "
            "collective knowledge — conversations, documents, relationships, "
            "and decisions."
        )

    def build_messages(
        self,
        new_question: str,
        knowledge_context: str = "",
        author_info: Optional[str] = None
    ) -> Tuple[str, List[Dict]]:
        """
        Build the system prompt and messages array for a Claude API call.

        Returns (system_prompt, messages) where:
        - system_prompt includes identity + knowledge context (cacheable)
        - messages has conversation history + new question

        The knowledge context goes in the system prompt (not in messages)
        because it's stable across turns in the same thread — this means
        it gets cached and isn't re-processed on follow-up questions.
        """
        # --- System prompt (stable per thread, cacheable) ---
        identity = self.get_system_prompt()
        system_parts = [identity]

        if knowledge_context:
            system_parts.append(
                f"## Available Knowledge\n\n{knowledge_context}"
            )

        system_parts.append(self._get_rules())
        system_prompt = "\n\n".join(system_parts)

        # --- Conversation history ---
        messages = []

        # Compacted summary of old turns (if any)
        thread = self._thread_repo.get_thread(self.thread_id)
        summary = thread.get('summary') if thread else None
        summary_through = thread.get('summary_through_turn_id') if thread else None

        if summary:
            messages.append({
                "role": "user",
                "content": f"[Earlier in this conversation: {summary}]"
            })
            messages.append({
                "role": "assistant",
                "content": "I have that context. Go ahead."
            })

        # Recent turns (after the summary cutoff)
        turns = self._thread_repo.get_turns(
            self.thread_id, after_turn_id=summary_through
        )
        for turn in turns:
            messages.append({
                "role": turn['role'],
                "content": turn['content']
            })

        # New question
        user_content = new_question
        if author_info:
            user_content = f"[{author_info}] {new_question}"
        messages.append({"role": "user", "content": user_content})

        return system_prompt, messages

    def add_exchange(
        self,
        question: str,
        answer: str,
        metadata: Optional[Dict] = None,
        author_info: Optional[str] = None
    ):
        """Store a question-answer exchange as two turns, then check compaction."""
        user_content = question
        if author_info:
            user_content = f"[{author_info}] {question}"

        self._thread_repo.add_turn(
            self.thread_id, 'user', user_content,
            metadata=metadata, token_estimate=estimate_tokens(user_content)
        )
        self._thread_repo.add_turn(
            self.thread_id, 'assistant', answer,
            metadata=metadata, token_estimate=estimate_tokens(answer)
        )

        self._maybe_compact()

    def _maybe_compact(self):
        """Compact old turns if total tokens exceed threshold."""
        turns = self._thread_repo.get_turns(self.thread_id)
        if not turns:
            return

        total_tokens = sum(
            t.get('token_estimate') or estimate_tokens(t['content'])
            for t in turns
        )

        if total_tokens < COMPACTION_THRESHOLD:
            return

        logger.info(f"Thread {self.thread_id}: {total_tokens} est. tokens, compacting")
        self._compact(turns)

    def _compact(self, turns: List[Dict]):
        """
        Summarize old turns, keep recent ones.
        Mirrors Claude Code's conversation compaction strategy.
        """
        if len(turns) < 4:
            return

        # Find split: keep last COMPACTION_KEEP_TOKENS of turns
        cumulative = 0
        keep_from_idx = len(turns)
        for i in range(len(turns) - 1, -1, -1):
            tokens = turns[i].get('token_estimate') or estimate_tokens(turns[i]['content'])
            cumulative += tokens
            if cumulative > COMPACTION_KEEP_TOKENS:
                keep_from_idx = i + 1
                break

        keep_from_idx = min(keep_from_idx, len(turns) - 2)
        if keep_from_idx <= 0:
            return

        old_turns = turns[:keep_from_idx]
        old_text = "\n".join(
            f"{t['role'].upper()}: {t['content'][:500]}"
            for t in old_turns
        )

        summary = self._generate_summary(old_text)
        if summary:
            self._thread_repo.update_summary(
                self.thread_id, summary, old_turns[-1]['id']
            )
            logger.info(
                f"Thread {self.thread_id}: compacted {len(old_turns)} turns "
                f"through turn {old_turns[-1]['id']}"
            )

    def _generate_summary(self, conversation_text: str) -> Optional[str]:
        """Use Claude to summarize old conversation turns."""
        api_key = os.getenv('ANTHROPIC_API_KEY')
        if not api_key:
            return conversation_text[:SUMMARY_MAX_TOKENS * CHARS_PER_TOKEN]

        try:
            client = Anthropic(api_key=api_key)
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=SUMMARY_MAX_TOKENS,
                messages=[{
                    "role": "user",
                    "content": (
                        "Summarize this conversation concisely. Preserve: key facts, "
                        "decisions made, questions answered, unresolved topics. "
                        "No pleasantries or meta-commentary.\n\n"
                        f"{conversation_text}"
                    )
                }]
            )
            return response.content[0].text
        except Exception as e:
            logger.warning(f"Summary generation failed: {e}")
            return conversation_text[:SUMMARY_MAX_TOKENS * CHARS_PER_TOKEN]

    def _get_rules(self) -> str:
        return """## Rules
1. Answer using ALL available knowledge — both project docs AND conversation history
2. Project & Reference Knowledge contains team docs, plans, and project descriptions — prioritize these for questions about projects, plans, strategy, or team work
3. If you don't have information, say so — don't invent
4. Attribute: say where information came from (source file, channel, who, when)
5. If sources disagree, name the tension
6. Be concise but thorough
7. Use *single asterisks* for bold (Slack-compatible)
8. No emojis"""

    def get_thread_info(self) -> Dict:
        """Thread metadata for debugging/display."""
        thread = self._thread_repo.get_thread(self.thread_id)
        turns = self._thread_repo.get_turns(self.thread_id)
        total_tokens = sum(
            t.get('token_estimate') or estimate_tokens(t['content'])
            for t in turns
        )
        return {
            'thread_id': self.thread_id,
            'source_type': self.source_type,
            'source_ref': self.source_ref,
            'turn_count': len(turns),
            'estimated_tokens': total_tokens,
            'has_summary': bool(thread.get('summary') if thread else False),
            'last_active': str(thread.get('last_active_at', ''))
        }


def apply_cache_control(
    system_prompt: str,
    messages: List[Dict]
) -> Tuple[List[Dict], List[Dict]]:
    """
    Apply prompt caching markers for the Claude API.

    Returns (system_blocks, cached_messages) ready for the API call.

    Strategy (matching Claude Code):
    - System prompt gets cache_control (stable across turns in a thread)
    - Second-to-last message gets cache_control (prefix through previous
      turn is cached, only the new question is fresh tokens)
    """
    system_blocks = [{
        "type": "text",
        "text": system_prompt,
        "cache_control": {"type": "ephemeral"}
    }]

    cached_messages = []
    for i, msg in enumerate(messages):
        if i == len(messages) - 2 and len(messages) >= 2:
            # Cache breakpoint on second-to-last message
            cached_messages.append({
                "role": msg["role"],
                "content": [{
                    "type": "text",
                    "text": msg["content"],
                    "cache_control": {"type": "ephemeral"}
                }]
            })
        else:
            cached_messages.append({
                "role": msg["role"],
                "content": msg["content"]
            })

    return system_blocks, cached_messages
