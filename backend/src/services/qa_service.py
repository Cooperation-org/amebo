"""
Q&A Service using RAG (Retrieval-Augmented Generation).
Answers questions based on Slack message history.
"""

import os
import re
import logging
from typing import List, Dict, Optional, Tuple
from anthropic import Anthropic

from src.services.query_service import QueryService

logger = logging.getLogger(__name__)


class QAService:
    """
    Q&A service that answers questions using RAG:
    1. Retrieve relevant messages (semantic search)
    2. Build context from messages
    3. Generate answer with LLM (Claude)
    """

    def __init__(self, workspace_id: str):
        """
        Initialize Q&A service.

        Args:
            workspace_id: Workspace ID (REQUIRED for security/isolation)

        Raises:
            ValueError: If workspace_id is None or empty
        """
        if not workspace_id:
            raise ValueError(
                "workspace_id is REQUIRED for Q&A service. "
                "This ensures workspace data isolation for security."
            )

        self.workspace_id = workspace_id
        self.query_service = QueryService(workspace_id)

        # Initialize Anthropic client
        api_key = os.getenv('ANTHROPIC_API_KEY')
        if api_key:
            self.client = Anthropic(api_key=api_key)
        else:
            logger.warning("ANTHROPIC_API_KEY not set - using mock responses")
            self.client = None

    def answer_question(
        self,
        question: str,
        n_context_messages: int = 10,
        channel_filter: Optional[str] = None,
        days_back: Optional[int] = None
    ) -> Dict:
        """
        Answer a question based on Slack history.

        Args:
            question: User's question
            n_context_messages: Number of messages to use as context
            channel_filter: Optional channel name filter
            days_back: Optional time filter

        Returns:
            Dict with answer, sources, confidence
        """
        logger.info(f"Answering question: {question}")

        # Auto-detect time-based questions if days_back not explicitly provided
        if days_back is None:
            days_back = self._detect_time_filter(question)

        # Auto-detect channel filter from question
        if channel_filter is None:
            channel_filter = self._detect_channel_filter(question)

        # 1. Retrieve relevant messages (semantic search)
        # Get more results than needed to allow filtering
        search_results = n_context_messages * 3
        relevant_messages = self.query_service.semantic_search(
            query=question,
            n_results=search_results,
            channel_filter=channel_filter,
            days_back=days_back
        )

        # 2. Filter out low-quality messages (bot notifications, joins, etc.)
        relevant_messages = self._filter_quality_messages(relevant_messages, n_context_messages)

        if not relevant_messages:
            # Provide helpful message based on filters
            filters_applied = []
            if days_back:
                filters_applied.append(f"last {days_back} days")
            if channel_filter:
                filters_applied.append(f"#{channel_filter} channel")

            if filters_applied:
                filters_str = " in the " + " and ".join(filters_applied)
                answer = f"I couldn't find any substantive messages{filters_str}. There may be very little activity during this period, or the messages might be too short/simple to be useful (like emoji reactions or join notifications).\n\nTry:\n• Asking about a different time period\n• Asking without specifying a channel\n• Asking about a more general topic"
            else:
                answer = "I couldn't find any relevant information in the Slack history to answer this question."

            return {
                'answer': answer,
                'sources': [],
                'confidence': 0,
                'confidence_explanation': 'No relevant messages found after filtering',
                'project_links': [],
                'context_used': 0
            }

        # 2. Build context from messages
        context = self._build_context(relevant_messages)

        # 3. Generate answer with LLM
        if self.client:
            answer = self._generate_answer_with_claude(question, context, relevant_messages)
        else:
            answer = self._generate_mock_answer(question, relevant_messages)

        return answer

    def _detect_time_filter(self, question: str) -> Optional[int]:
        """
        Detect if question is time-based and return appropriate days_back filter.

        Args:
            question: User's question

        Returns:
            Number of days to look back, or None for no filter
        """
        question_lower = question.lower()

        # Time-based keywords
        time_patterns = {
            'today': 1,
            'yesterday': 2,
            'this week': 7,
            'past week': 7,
            'last week': 14,  # Look back 2 weeks to include last week
            'this month': 30,
            'past month': 30,
            'last month': 60,  # Look back 2 months to include last month
            'recent': 7,
            'recently': 7,
            'latest': 7,
        }

        for pattern, days in time_patterns.items():
            if pattern in question_lower:
                logger.info(f"Detected time filter '{pattern}' -> {days} days")
                return days

        # Default: no time filter (search all history)
        return None

    def _detect_channel_filter(self, question: str) -> Optional[str]:
        """
        Detect if question mentions a specific channel.

        Args:
            question: User's question

        Returns:
            Channel name (without #) or None
        """
        question_lower = question.lower()

        # Common channel names
        channel_keywords = [
            'general', 'standup', 'hackathons', 'random', 'engineering',
            'design', 'product', 'marketing', 'sales', 'support',
            'dev', 'testing', 'qa', 'operations', 'announcements'
        ]

        for channel in channel_keywords:
            # Match patterns like "in #general", "in general channel", "general channel"
            if f'#{channel}' in question_lower or f'{channel} channel' in question_lower or f'in {channel}' in question_lower:
                logger.info(f"Detected channel filter: {channel}")
                return channel

        return None

    def _filter_quality_messages(self, messages: List[Dict], limit: int) -> List[Dict]:
        """
        Filter out low-quality messages (bot notifications, joins, etc.).

        Args:
            messages: List of messages from search
            limit: Maximum number of messages to return

        Returns:
            Filtered list of quality messages
        """
        quality_messages = []

        for msg in messages:
            text = msg.get('text', '').lower()

            # Skip if message is too short
            if len(text.strip()) < 10:
                continue

            # Skip common bot notification patterns
            skip_patterns = [
                'has joined the channel',
                'has left the channel',
                'set the channel topic',
                'set the channel description',
                'uploaded a file',
                'renamed the channel',
                'archived the channel',
                'pinned a message',
            ]

            if any(pattern in text for pattern in skip_patterns):
                continue

            # Skip if message is mostly mentions (like "@user @user @user")
            mention_count = text.count('<@')
            word_count = len(text.split())
            if word_count > 0 and mention_count / word_count > 0.5:
                continue

            quality_messages.append(msg)

            # Stop once we have enough quality messages
            if len(quality_messages) >= limit:
                break

        logger.info(f"Filtered {len(messages)} messages down to {len(quality_messages)} quality messages")
        return quality_messages

    def _build_context(self, messages: List[Dict]) -> str:
        """
        Build context string from relevant messages with channel-based citations.

        Args:
            messages: List of relevant messages

        Returns:
            Formatted context string
        """
        context_parts = []

        for i, msg in enumerate(messages, 1):
            metadata = msg['metadata']
            channel_name = metadata.get('channel_name', 'unknown')
            user_name = metadata.get('user_name', 'unknown')

            context_parts.append(
                f"[#{channel_name}] (from {user_name}):\n{msg['text']}"
            )

        return "\n\n".join(context_parts)

    def _generate_answer_with_claude(
        self,
        question: str,
        context: str,
        messages: List[Dict]
    ) -> Dict:
        """
        Generate answer using Claude API.

        Args:
            question: User's question
            context: Context from messages
            messages: Original messages for sources

        Returns:
            Answer dict
        """
        system_prompt = """You are a precise Q&A assistant for Slack workspace history.

**Critical Rules:**
1. ONLY answer based on the provided messages - NO external knowledge or assumptions
2. If messages don't contain the answer, say "I don't have information about this in the Slack history"
3. NEVER make assumptions or add information not explicitly in the messages
4. Be thorough and include ALL relevant details from the messages

**How Messages Are Formatted:**
Each message shows its channel name in brackets like [#hackathons] or [#standup].

**Your Answer Must:**
- Use inline citations with channel names: [#hackathons], [#general], [#standup]
- Place citations immediately after relevant statements
- Example: "The team is working on the dashboard [#general]"
- Include URLs inline in your text (e.g., "The repo is at https://github.com/...")
- Use *bold* for emphasis (single asterisk, not double **)
- Use _italic_ for secondary emphasis
- Write in clear paragraphs
- Be comprehensive - include all relevant details, dates, names, features, URLs

**What NOT to Include:**
- Do NOT add emoji or emoji codes (:link:, :large_yellow_circle:, etc.)
- Do NOT add a "Confidence:" line
- Do NOT create a separate "Related Links:" section
- Do NOT use ## headers or **double asterisks**
- Do NOT add a "Sources:" section"""

        user_prompt = f"""Question: {question}

Slack Message History:
{context}

Answer the question based on these messages. Be comprehensive and include all relevant details."""

        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1000,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_prompt}
                ]
            )

            answer_text = response.content[0].text

            # Extract confidence percentage and explanation (and remove from answer)
            confidence, confidence_explanation = self._extract_confidence(answer_text)

            # Remove confidence line from answer text (handles emoji codes too)
            confidence_pattern = r':?\w*:?\s*\*?\*?Confidence:\s*\d+%\s*\*?\*?\s*[-–]\s*.+?(?:\n|$)'
            answer_text = re.sub(confidence_pattern, '', answer_text, flags=re.IGNORECASE | re.MULTILINE).strip()

            # Remove any standalone "Related Links:" or "Sources:" sections Claude might add
            # This handles variations like ":link: Related Links:" or "**Sources:**"
            answer_text = re.sub(r':?\w*:?\s*\*{0,2}Related Links?:?\*{0,2}\s*\n.*?(?=\n\n|\Z)', '', answer_text, flags=re.IGNORECASE | re.DOTALL)
            answer_text = re.sub(r':?\w*:?\s*\*{0,2}Sources?:?\*{0,2}\s*\n.*?(?=\n\n|\Z)', '', answer_text, flags=re.IGNORECASE | re.DOTALL)

            # Remove numbered source citations like "[1] #standup - user: text..."
            answer_text = re.sub(r'\[\d+\]\s+#[\w-]+\s+-\s+[^:]*:\s+_[^_]+_\n?', '', answer_text)

            # Remove emoji shortcodes from the entire answer
            answer_text = re.sub(r':[\w_]+:', '', answer_text)

            # Clean up extra blank lines
            answer_text = re.sub(r'\n{3,}', '\n\n', answer_text).strip()

            # Extract project links from messages
            project_links = self._extract_project_links(messages)

            return {
                'answer': answer_text,
                'sources': self._format_sources(messages),
                'confidence': confidence,
                'confidence_explanation': confidence_explanation,
                'project_links': project_links,
                'context_used': len(messages),
                'model': 'claude-3-5-sonnet'
            }

        except Exception as e:
            logger.error(f"Failed to generate answer with Claude: {e}")
            return {
                'answer': f"I found relevant messages but encountered an error generating an answer: {str(e)}",
                'sources': self._format_sources(messages),
                'confidence': 0,
                'confidence_explanation': f'Error: {str(e)}',
                'project_links': [],
                'context_used': len(messages)
            }

    def _generate_mock_answer(
        self,
        question: str,
        messages: List[Dict]
    ) -> Dict:
        """
        Generate mock answer (when API key not available).

        Args:
            question: User's question
            messages: Relevant messages

        Returns:
            Mock answer dict
        """
        # Simple mock: return the most relevant message
        top_message = messages[0] if messages else None

        if top_message:
            answer = (
                f"Based on the Slack history, here's what I found:\n\n"
                f"{top_message['text'][:300]}...\n\n"
                f"(This was mentioned in #{top_message['metadata']['channel_name']} "
                f"by {top_message['metadata']['user_name']})"
            )
        else:
            answer = "I couldn't find relevant information to answer this question."

        return {
            'answer': answer,
            'sources': self._format_sources(messages),
            'confidence': 50,
            'confidence_explanation': 'Mock mode - medium confidence estimate',
            'project_links': self._extract_project_links(messages),
            'context_used': len(messages),
            'model': 'mock'
        }

    def _extract_confidence(self, answer: str) -> Tuple[int, str]:
        """
        Extract confidence percentage from Claude's answer.

        Args:
            answer: Generated answer with confidence line

        Returns:
            Tuple of (confidence percentage 0-100, explanation string)
        """
        # Look for "Confidence: X% - explanation" pattern (with emoji codes, ** or without)
        confidence_pattern = r':?\w*:?\s*\*?\*?Confidence:\s*(\d+)%\s*\*?\*?\s*[-–]\s*(.+?)(?:\n|$)'
        match = re.search(confidence_pattern, answer, re.IGNORECASE | re.MULTILINE)

        if match:
            confidence = int(match.group(1))
            explanation = match.group(2).strip()
            # Remove emoji codes from explanation
            explanation = re.sub(r':[\w_]+:', '', explanation).strip()
            return confidence, explanation

        # Fallback: assess based on content
        answer_lower = answer.lower()

        if any(phrase in answer_lower for phrase in [
            "couldn't find", "don't have", "no information"
        ]):
            return 10, "No relevant information found"

        if any(phrase in answer_lower for phrase in [
            "not sure", "unclear", "uncertain"
        ]):
            return 30, "Limited or unclear information"

        if any(phrase in answer_lower for phrase in [
            "might", "possibly", "seems"
        ]):
            return 55, "Some relevant information but not definitive"

        # Default medium confidence
        return 65, "Relevant information found"

    def _extract_project_links(self, messages: List[Dict]) -> List[Dict]:
        """
        Extract GitHub repos and documentation links from messages.

        Args:
            messages: List of messages

        Returns:
            List of found links with metadata
        """
        links = []
        seen_urls = set()

        # Regex patterns for project-related URLs
        github_pattern = r'https?://(?:www\.)?github\.com/[\w\-]+/[\w\-.]+'
        docs_patterns = [
            r'https?://[\w\-]+\.(?:readthedocs\.io|github\.io)/[\w\-./]*',
            r'https?://docs?\.[\w\-]+\.[a-z]{2,}/[\w\-./]*',
        ]

        for msg in messages:
            text = msg.get('text', '')
            metadata = msg.get('metadata', {})

            # Extract GitHub repos
            for match in re.finditer(github_pattern, text, re.IGNORECASE):
                url = match.group(0).rstrip('.,!?)')
                if url not in seen_urls:
                    seen_urls.add(url)
                    links.append({
                        'type': 'github',
                        'url': url,
                        'source_channel': metadata.get('channel_name', 'unknown')
                    })

            # Extract documentation links
            for pattern in docs_patterns:
                for match in re.finditer(pattern, text, re.IGNORECASE):
                    url = match.group(0).rstrip('.,!?)')
                    if url not in seen_urls:
                        seen_urls.add(url)
                        links.append({
                            'type': 'documentation',
                            'url': url,
                            'source_channel': metadata.get('channel_name', 'unknown')
                        })

        return links

    def _format_sources(self, messages: List[Dict]) -> List[Dict]:
        """
        Format source messages for response with reference numbers.
        Looks up usernames from database if not in metadata.

        Args:
            messages: Relevant messages

        Returns:
            List of formatted source dicts
        """
        from src.db.connection import DatabaseConnection

        sources = []

        # Collect user IDs that need lookup
        user_ids_to_lookup = set()
        for msg in messages[:10]:
            metadata = msg['metadata']
            if not metadata.get('user_name'):
                user_id = metadata.get('user_id')
                if user_id:
                    user_ids_to_lookup.add(user_id)

        # Lookup usernames if needed
        user_map = {}
        if user_ids_to_lookup:
            conn = DatabaseConnection.get_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT user_id, COALESCE(display_name, real_name, user_name) as name
                        FROM users
                        WHERE workspace_id = %s AND user_id = ANY(%s)
                        """,
                        (self.workspace_id, list(user_ids_to_lookup))
                    )
                    user_map = {row[0]: row[1] for row in cur.fetchall()}
            finally:
                DatabaseConnection.return_connection(conn)

        # Format sources
        for i, msg in enumerate(messages[:10], 1):  # Top 10 sources
            metadata = msg['metadata']
            channel = metadata.get('channel_name', '') or 'unknown'

            # Get username from metadata or lookup
            user_id = metadata.get('user_id', '')
            user = metadata.get('user_name', '') or user_map.get(user_id, 'unknown')

            sources.append({
                'reference_number': i,
                'text': msg['text'][:200] + ('...' if len(msg['text']) > 200 else ''),
                'channel': channel,
                'user': user,
                'timestamp': metadata.get('timestamp', ''),
                'distance': msg.get('distance', 0)
            })

        return sources

    def answer_with_follow_up(
        self,
        question: str,
        conversation_history: Optional[List[Dict]] = None
    ) -> Dict:
        """
        Answer question with conversation context (for multi-turn Q&A).

        Args:
            question: User's question
            conversation_history: Previous Q&A turns

        Returns:
            Answer dict
        """
        # For now, just answer the question
        # In future, use conversation_history to maintain context
        return self.answer_question(question)

    def suggest_related_questions(
        self,
        original_question: str,
        n_suggestions: int = 3
    ) -> List[str]:
        """
        Suggest related follow-up questions.

        Args:
            original_question: Original question asked
            n_suggestions: Number of suggestions

        Returns:
            List of suggested questions
        """
        # Get context from original question
        relevant_messages = self.query_service.semantic_search(
            query=original_question,
            n_results=20
        )

        if not relevant_messages:
            return []

        # Extract topics/keywords from messages
        # In production, use LLM to generate better suggestions
        suggestions = [
            "Who is the expert on this topic?",
            "When was this last discussed?",
            "Are there any related GitHub PRs?"
        ]

        return suggestions[:n_suggestions]


if __name__ == "__main__":
    # Test the Q&A service
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    print("Testing Q&A Service...\n")

    qa = QAService(workspace_id='W_DEFAULT')

    # Test questions
    test_questions = [
        "What hackathon projects are people working on?",
        "How do I join the hackathon?",
        "What are people building in the standup channel?"
    ]

    for i, question in enumerate(test_questions, 1):
        print(f"\n{'='*60}")
        print(f"Question {i}: {question}")
        print('='*60)

        result = qa.answer_question(question, n_context_messages=5)

        print(f"\nAnswer ({result['confidence']} confidence):")
        print(result['answer'])

        print(f"\nSources ({result['context_used']} messages used):")
        for j, source in enumerate(result['sources'][:3], 1):
            print(f"  {j}. #{source['channel']} - {source['user']}")
            print(f"     {source['text'][:80]}...")

    print("\n" + "="*60)
    print("✅ Q&A Service test complete!")

    from src.db.connection import DatabaseConnection
    DatabaseConnection.close_all_connections()
