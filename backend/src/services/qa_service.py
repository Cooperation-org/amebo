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
        import re

        # First, check for Slack channel mention format: <#CHANNELID> or <#CHANNELID|name>
        channel_mention_pattern = r'<#([A-Z0-9]+)(?:\|([a-zA-Z0-9_-]+))?>'
        matches = re.findall(channel_mention_pattern, question)

        if matches:
            channel_id, channel_name = matches[0]

            # If channel name is provided in the mention, use it
            if channel_name:
                logger.info(f"Detected channel filter from mention: {channel_name} ({channel_id})")
                return channel_name

            # Otherwise, look up channel name from database using channel_id
            try:
                from src.db.connection import DatabaseConnection
                conn = DatabaseConnection.get_connection()
                cur = conn.cursor()

                cur.execute(
                    "SELECT channel_name FROM channels WHERE channel_id = %s",
                    (channel_id,)
                )
                row = cur.fetchone()

                cur.close()
                conn.close()

                if row:
                    channel_name = row[0]
                    logger.info(f"Detected channel filter from ID lookup: {channel_name} ({channel_id})")
                    return channel_name
                else:
                    # If not in database, just use the channel_id as filter
                    logger.info(f"Detected channel ID filter: {channel_id}")
                    return channel_id

            except Exception as e:
                logger.warning(f"Error looking up channel name for {channel_id}: {e}")
                # Fall back to using channel_id
                return channel_id

        # Fall back to checking for common channel names
        question_lower = question.lower()

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

            # Parse user mentions in message text and replace with names
            message_text = self._parse_user_mentions(msg['text'])

            context_parts.append(
                f"[#{channel_name}] (from {user_name}):\n{message_text}"
            )

        return "\n\n".join(context_parts)

    def _parse_user_mentions(self, text: str) -> str:
        """
        Parse user mentions in Slack message format (<@USERID>) and replace with usernames.

        Args:
            text: Message text with user mentions

        Returns:
            Text with mentions replaced by names
        """
        import re
        from src.db.connection import DatabaseConnection

        # Find all user mentions in format <@USERID> or <@USERID|username>
        mention_pattern = r'<@([A-Z0-9]+)(?:\|([^>]+))?>'
        matches = re.findall(mention_pattern, text)

        if not matches:
            return text

        # Build a map of user IDs to names
        user_ids = [match[0] for match in matches]
        user_map = {}

        try:
            conn = DatabaseConnection.get_connection()
            cur = conn.cursor()

            # Look up usernames from users table
            cur.execute(
                """
                SELECT user_id, real_name, display_name
                FROM users
                WHERE workspace_id = %s AND user_id = ANY(%s)
                """,
                (self.workspace_id, user_ids)
            )

            for row in cur.fetchall():
                user_id, real_name, display_name = row
                # Prefer display_name, fall back to real_name
                user_map[user_id] = display_name or real_name or user_id

            cur.close()
            conn.close()

        except Exception as e:
            logger.warning(f"Error looking up user mentions: {e}")

        # Replace mentions in text
        def replace_mention(match):
            user_id = match.group(1)
            username_in_mention = match.group(2)  # From <@USERID|username> format

            # Use the username if provided in the mention, otherwise lookup
            if username_in_mention:
                return f"@{username_in_mention}"
            elif user_id in user_map:
                return f"@{user_map[user_id]}"
            else:
                # Fall back to showing the ID if we can't resolve it
                return f"@{user_id}"

        return re.sub(mention_pattern, replace_mention, text)

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
        system_prompt = """You are a helpful teammate answering questions about your Slack workspace.

**Critical Rules (NEVER BREAK THESE):**
1. ONLY answer based on the provided messages - NO external knowledge or assumptions
2. If messages don't contain the answer, say "I don't have recent info on this in the Slack history"
3. NEVER make assumptions or add information not explicitly in the messages
4. Be thorough and include ALL relevant details from the messages

**Your Personality:**
- Conversational and friendly, like chatting with a coworker
- Professional but approachable
- Call out blockers, issues, or important context naturally

**Response Structure:**

1. START with a casual greeting (vary it):
   - "Hey!" / "So..." / "Alright," / "Yeah," / or just start with the answer

2. ANSWER the question naturally in 2-4 sentences:
   - Include key details (who, what, when, blockers)
   - Mention blockers explicitly if present (use words like "blocker", "blocked by", "waiting on", "issue")
   - Be specific with names, dates, and context
   - Include URLs inline when relevant (e.g., "The repo is at https://github.com/...")

3. DO NOT add a "What I found:" section - just provide the answer

**Formatting (IMPORTANT - This is for Slack, not Markdown):**
- Use *single asterisks* for bold (NOT double asterisks like **this**)
- Example: *important term* NOT **important term**
- Use _underscores_ for italic
- Write in clear paragraphs
- NO emojis or emoji codes
- NO separate "Sources:" or "Confidence:" sections
- Keep it concise but informative"""

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

            # Convert markdown bold (**text**) to Slack bold (*text*)
            # This ensures compatibility even if Claude doesn't follow instructions
            answer_text = re.sub(r'\*\*([^\*]+?)\*\*', r'*\1*', answer_text)

            # Clean up extra blank lines
            answer_text = re.sub(r'\n{3,}', '\n\n', answer_text).strip()

            # Extract project links from messages
            project_links = self._extract_project_links(messages)

            # Format with Style A sources (conversational with "What I found:")
            formatted_answer = self._format_style_a_response(
                answer_text,
                messages,
                max_sources=3
            )

            return {
                'answer': formatted_answer,
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
        # Simple mock: return the most relevant message in Style A format
        if messages:
            top_message = messages[0]
            user = top_message['metadata'].get('user_name', 'someone')
            channel = top_message['metadata'].get('channel_name', 'unknown')

            answer = (
                f"Hey! Based on what I saw, {user} mentioned this in #{channel}. "
                f"{top_message['text'][:200]}"
            )

            # Add Style A sources
            formatted_answer = self._format_style_a_response(
                answer,
                messages,
                max_sources=3
            )
        else:
            formatted_answer = "I couldn't find relevant information to answer this question."

        return {
            'answer': formatted_answer,
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

    def _format_friendly_timestamp(self, timestamp: str) -> str:
        """
        Format timestamp in friendly format like 'Dec 15, 2pm'.

        Args:
            timestamp: ISO timestamp or Slack timestamp

        Returns:
            Friendly formatted timestamp
        """
        from datetime import datetime

        try:
            # Handle Slack timestamp (Unix timestamp with decimal)
            if '.' in timestamp and len(timestamp.split('.')[0]) == 10:
                dt = datetime.fromtimestamp(float(timestamp))
            else:
                # Handle ISO format
                dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))

            # Format as "Dec 15, 2pm"
            month = dt.strftime('%b')
            day = dt.day
            hour = dt.hour

            # Convert to 12-hour format
            if hour == 0:
                time_str = "12am"
            elif hour < 12:
                time_str = f"{hour}am"
            elif hour == 12:
                time_str = "12pm"
            else:
                time_str = f"{hour-12}pm"

            return f"{month} {day}, {time_str}"
        except Exception:
            return "recently"

    def _format_style_a_response(
        self,
        answer_text: str,
        messages: List[Dict],
        max_sources: int = 3
    ) -> str:
        """
        Format response in Style A with 'What I found:' section.

        Args:
            answer_text: Claude's generated answer
            messages: Source messages
            max_sources: Maximum sources to show (default 3)

        Returns:
            Formatted response with sources
        """
        # Build "What I found:" section
        if not messages:
            return answer_text

        sources_lines = ["\n\nWhat I found:"]

        for i, msg in enumerate(messages[:max_sources], 1):
            metadata = msg['metadata']
            channel = metadata.get('channel_name', 'unknown')
            user = metadata.get('user_name', 'unknown')
            timestamp_str = self._format_friendly_timestamp(metadata.get('timestamp', ''))

            # Get quote (truncate if too long)
            quote = msg['text'].strip()
            if len(quote) > 150:
                quote = quote[:147] + "..."

            # Format: • User's update in #channel (timestamp): "quote"
            sources_lines.append(
                f'• {user}\'s update in #{channel} ({timestamp_str}): "{quote}"'
            )

        # Add indicator if there are more sources
        if len(messages) > max_sources:
            sources_lines.append(f"\n...and {len(messages) - max_sources} more")

        return answer_text + "\n".join(sources_lines)

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
    print("Q&A Service test complete!")

    from src.db.connection import DatabaseConnection
    DatabaseConnection.close_all_connections()
