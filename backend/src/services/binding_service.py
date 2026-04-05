"""
Binding service — business logic for structured knowledge (abra bindings).
Wraps binding_repo with higher-level operations.
"""

import logging
from typing import List, Dict, Optional
from src.db.repositories.binding_repo import BindingRepo

logger = logging.getLogger(__name__)


class BindingService:
    """High-level operations on bindings for use by QA and API routes."""

    def __init__(self, org_id: int = None):
        self.org_id = org_id
        self.repo = BindingRepo(org_id)

    def about(
        self,
        name: str,
        scope: Optional[str] = None,
        workspace_id: Optional[str] = None
    ) -> Dict:
        """
        Everything known about a name: bindings + hot status.
        Returns structured dict for use in QA enrichment.
        """
        bindings = self.repo.search_bindings_by_name(name, scope, workspace_id)
        is_hot = self.repo.is_hot(name, scope)

        # Group bindings by relationship type
        by_relationship = {}
        for b in bindings:
            rel = b['relationship']
            if rel not in by_relationship:
                by_relationship[rel] = []
            by_relationship[rel].append(b)

        # Fetch linked content for ABOUT bindings
        content_refs = []
        for b in bindings:
            if b['target_type'] == 'content':
                try:
                    content_id = int(b['target_ref'])
                    content = self.repo.get_content(content_id)
                    if content:
                        content_refs.append({
                            'binding_id': b['id'],
                            'qualifier': b['qualifier'],
                            'content_preview': content['content'][:500]
                        })
                except (ValueError, TypeError):
                    pass

        return {
            'name': name,
            'is_hot': is_hot,
            'binding_count': len(bindings),
            'bindings': bindings,
            'by_relationship': by_relationship,
            'content_refs': content_refs
        }

    def enrich_names(
        self,
        names: List[str],
        scope: Optional[str] = None
    ) -> Dict[str, Dict]:
        """
        Batch lookup bindings for multiple names.
        Returns dict keyed by name with binding summaries.
        Used by QA pipeline to enrich search results.
        """
        if not names:
            return {}

        bindings = self.repo.search_bindings_by_names(names, scope)

        # Group by name
        by_name = {}
        for b in bindings:
            name_lower = b['name'].lower()
            if name_lower not in by_name:
                by_name[name_lower] = {
                    'name': b['name'],
                    'bindings': [],
                    'relationships': set()
                }
            by_name[name_lower]['bindings'].append(b)
            by_name[name_lower]['relationships'].add(b['relationship'])

        # Check hot tags for all names
        hot_tags = self.repo.get_hot_tags(scope)
        hot_names = {ht['name'].lower() for ht in hot_tags}

        result = {}
        for name_lower, data in by_name.items():
            data['relationships'] = list(data['relationships'])
            data['is_hot'] = name_lower in hot_names
            result[name_lower] = data

        return result

    def get_hot_context(self, scope: Optional[str] = None) -> List[Dict]:
        """Get all hot tags with their binding summaries."""
        hot_tags = self.repo.get_hot_tags(scope)
        results = []
        for ht in hot_tags:
            bindings = self.repo.search_bindings_by_name(ht['name'], scope)
            results.append({
                'name': ht['name'],
                'scope': ht['scope'],
                'priority': ht['priority'],
                'binding_count': len(bindings),
                'relationships': list({b['relationship'] for b in bindings})
            })
        return results

    def format_for_prompt(self, enrichment: Dict[str, Dict]) -> str:
        """
        Format binding enrichment data as text for inclusion in LLM prompt.
        Concise structured output that adds context without overwhelming.
        """
        if not enrichment:
            return ""

        lines = ["Known relationships and context:"]
        for name_lower, data in enrichment.items():
            name = data['name']
            hot_marker = " [PRIORITY]" if data.get('is_hot') else ""
            lines.append(f"\n{name}{hot_marker}:")

            for b in data['bindings'][:5]:  # Cap at 5 bindings per name
                rel = b['relationship']
                target = b['target_ref']
                qual = f" ({b['qualifier']})" if b.get('qualifier') else ""
                lines.append(f"  - {rel} {target}{qual}")

        return "\n".join(lines)
