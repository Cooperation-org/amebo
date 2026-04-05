"""
Trust service — query live.linkedtrust.us for LinkedClaims about entities.

STUB: Methods defined with signatures and return shapes, but not yet
connected to the actual API. Fill in as the QA pipeline discovers what
trust information it needs.

See ~/work/4-4-2026-trust-needs.md for the running list of needs.
"""

import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

LINKEDTRUST_API = "https://live.linkedtrust.us"


class TrustService:
    """Query LinkedClaims for trust information about entities."""

    def __init__(self, base_url: str = LINKEDTRUST_API):
        self.base_url = base_url

    async def get_claims_about(
        self,
        subject: str,
        claim_type: Optional[str] = None
    ) -> List[Dict]:
        """
        Get claims where subject is the target.

        Args:
            subject: Entity name or identifier
            claim_type: Optional filter (e.g., 'contribution', 'skill', 'endorsement')

        Returns:
            List of claim dicts. Shape TBD — at minimum:
            [{'subject': str, 'claim': str, 'source': str, 'date': str, 'stars': int}]
        """
        # TODO: implement against live.linkedtrust.us/api/claim endpoint
        logger.debug(f"trust_service.get_claims_about({subject}) — stub, returning empty")
        return []

    async def get_claims_by(
        self,
        source: str,
        claim_type: Optional[str] = None
    ) -> List[Dict]:
        """
        Get claims made BY a source (what has this entity attested?).

        Args:
            source: Entity that made the claims
            claim_type: Optional filter

        Returns:
            List of claim dicts
        """
        # TODO: implement
        return []

    async def get_trust_score(
        self,
        subject: str,
        aspect: Optional[str] = None
    ) -> Dict:
        """
        Aggregate trust score for an entity.

        Args:
            subject: Entity to score
            aspect: Optional aspect (e.g., 'technical', 'reliability', 'domain')

        Returns:
            {
                'subject': str,
                'score': float or None,  # 0.0-1.0, None if insufficient data
                'claims_count': int,
                'aspect': str or None,
                'confidence': float or None  # how much data backs this score
            }
        """
        # TODO: define scoring model
        # Beyond thumbs up/down:
        # - weighted by attester's own trust score (recursive)
        # - recency-weighted (recent claims count more)
        # - aspect-specific
        return {
            'subject': subject,
            'score': None,
            'claims_count': 0,
            'aspect': aspect,
            'confidence': None
        }

    async def verify_contribution(
        self,
        person: str,
        project: str
    ) -> Dict:
        """
        Check if a person's contribution to a project has been peer-reviewed
        and attested via LinkedClaims.

        Returns:
            {
                'person': str,
                'project': str,
                'verified': bool,
                'attestations': List[Dict],  # who attested, when
                'confidence': float or None
            }
        """
        # TODO: implement
        return {
            'person': person,
            'project': project,
            'verified': False,
            'attestations': [],
            'confidence': None
        }
