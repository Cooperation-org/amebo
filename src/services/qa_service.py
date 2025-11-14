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
            workspace_id: Workspace ID
        """
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

        # 1. Retrieve relevant messages (semantic search)
        relevant_messages = self.query_service.semantic_search(
            query=question,
            n_results=n_context_messages,
            channel_filter=channel_filter,
            days_back=days_back
        )

        if not relevant_messages:
            return {
                'answer': "I couldn't find any relevant information in the Slack history to answer this question.",
                'sources': [],
                'confidence': 0,
                'confidence_explanation': 'No relevant messages found',
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

    def _build_context(self, messages: List[Dict]) -> str:
        """
        Build context string from relevant messages with inline numbering.

        Args:
            messages: List of relevant messages

        Returns:
            Formatted context string
        """
        context_parts = []

        for i, msg in enumerate(messages, 1):
            metadata = msg['metadata']
            context_parts.append(
                f"[{i}] Channel: #{metadata.get('channel_name', 'unknown')} | "
                f"User: {metadata.get('user_name', 'unknown')}\n"
                f"{msg['text']}"
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
2. Use inline citations [1], [2] when referencing specific messages (like academic papers)
3. If messages don't contain the answer, say "I don't have information about this in the Slack history"
4. NEVER make assumptions or add information not explicitly in the messages
5. When discussing projects/tools, include any GitHub repos or documentation links mentioned in the messages

**Citation Format:**
- Use [1], [2], [3] to cite messages (e.g., "The team is working on the dashboard [1][3]")
- Place citations immediately after the relevant statement
- Multiple citations can be combined [1][2]

**Confidence Assessment:**
After your answer, on a new line add:
Confidence: X% - [brief explanation of why this confidence level]

Base confidence on:
- 80-100%: Multiple messages confirm the same information
- 60-79%: Information found but limited confirmation
- 40-59%: Somewhat relevant but indirect information
- 20-39%: Very limited or ambiguous information
- 0-19%: Almost no relevant information found

**Project Links:**
If the question is about a project/tool and messages contain GitHub repos or docs, include them at the end."""

        user_prompt = f"""Question: {question}

Slack Message History:
{context}

Please answer the question based on these messages. Cite message numbers when relevant."""

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

            # Extract confidence percentage and explanation
            confidence, confidence_explanation = self._extract_confidence(answer_text)

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
        # Look for "Confidence: X% - explanation" pattern
        confidence_pattern = r'Confidence:\s*(\d+)%\s*[-–]\s*(.+?)(?:\n|$)'
        match = re.search(confidence_pattern, answer, re.IGNORECASE)

        if match:
            confidence = int(match.group(1))
            explanation = match.group(2).strip()
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

        Args:
            messages: Relevant messages

        Returns:
            List of formatted source dicts
        """
        sources = []

        for i, msg in enumerate(messages[:10], 1):  # Top 10 sources
            metadata = msg['metadata']
            sources.append({
                'reference_number': i,
                'text': msg['text'][:200] + ('...' if len(msg['text']) > 200 else ''),
                'channel': metadata.get('channel_name', 'unknown'),
                'user': metadata.get('user_name', 'unknown'),
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
