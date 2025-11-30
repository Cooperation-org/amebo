"""
CRITICAL SECURITY TESTS: Workspace Data Isolation

These tests verify that workspace data is completely isolated.
One organization must NEVER be able to access another organization's workspace data.

If ANY of these tests fail, it's a CRITICAL SECURITY VULNERABILITY.
"""

import pytest
from src.services.qa_service import QAService
from src.services.query_service import QueryService
from src.db.connection import DatabaseConnection
from src.db.chromadb_client import ChromaDBClient


class TestWorkspaceIsolation:
    """
    Test suite to ensure complete workspace isolation.
    THESE TESTS MUST ALL PASS before deploying to production.
    """

    @pytest.fixture(autouse=True)
    def setup_test_data(self):
        """Setup two separate organizations with different workspaces"""
        conn = DatabaseConnection.get_connection()
        cur = conn.cursor()

        # Clean up any existing test data
        cur.execute("DELETE FROM org_workspaces WHERE workspace_id LIKE 'TEST_%'")
        cur.execute("DELETE FROM workspaces WHERE workspace_id LIKE 'TEST_%'")
        cur.execute("DELETE FROM organizations WHERE org_name LIKE 'Test Org %'")
        conn.commit()

        # Create Org A
        cur.execute("""
            INSERT INTO organizations (org_name, org_slug)
            VALUES ('Test Org A', 'test-org-a')
            RETURNING org_id
        """)
        self.org_a_id = cur.fetchone()[0]

        # Create Org B
        cur.execute("""
            INSERT INTO organizations (org_name, org_slug)
            VALUES ('Test Org B', 'test-org-b')
            RETURNING org_id
        """)
        self.org_b_id = cur.fetchone()[0]

        # Create Workspace A (for Org A)
        cur.execute("""
            INSERT INTO workspaces (workspace_id, team_name)
            VALUES ('TEST_WORKSPACE_A', 'Test Team A')
        """)
        cur.execute("""
            INSERT INTO org_workspaces (org_id, workspace_id)
            VALUES (%s, 'TEST_WORKSPACE_A')
        """, (self.org_a_id,))

        # Create Workspace B (for Org B)
        cur.execute("""
            INSERT INTO workspaces (workspace_id, team_name)
            VALUES ('TEST_WORKSPACE_B', 'Test Team B')
        """)
        cur.execute("""
            INSERT INTO org_workspaces (org_id, workspace_id)
            VALUES (%s, 'TEST_WORKSPACE_B')
        """, (self.org_b_id,))

        conn.commit()

        # Insert test messages for Workspace A
        cur.execute("""
            INSERT INTO message_metadata
            (workspace_id, slack_ts, channel_id, channel_name, user_id, message_type, created_at)
            VALUES
            ('TEST_WORKSPACE_A', '1000000001', 'C001', 'general', 'U001', 'regular', NOW()),
            ('TEST_WORKSPACE_A', '1000000002', 'C001', 'general', 'U002', 'regular', NOW())
        """)

        # Insert test messages for Workspace B
        cur.execute("""
            INSERT INTO message_metadata
            (workspace_id, slack_ts, channel_id, channel_name, user_id, message_type, created_at)
            VALUES
            ('TEST_WORKSPACE_B', '2000000001', 'C002', 'general', 'U003', 'regular', NOW()),
            ('TEST_WORKSPACE_B', '2000000002', 'C002', 'general', 'U004', 'regular', NOW())
        """)

        conn.commit()

        # Add messages to ChromaDB
        chromadb_client = ChromaDBClient()

        # Messages for Workspace A
        chromadb_client.add_message(
            workspace_id='TEST_WORKSPACE_A',
            message_id=1,
            slack_ts='1000000001',
            message_text='Secret data for Organization A - Project Alpha',
            metadata={
                'workspace_id': 'TEST_WORKSPACE_A',
                'channel_name': 'general',
                'user_id': 'U001'
            }
        )

        chromadb_client.add_message(
            workspace_id='TEST_WORKSPACE_A',
            message_id=2,
            slack_ts='1000000002',
            message_text='Confidential info for Org A - Budget details',
            metadata={
                'workspace_id': 'TEST_WORKSPACE_A',
                'channel_name': 'general',
                'user_id': 'U002'
            }
        )

        # Messages for Workspace B
        chromadb_client.add_message(
            workspace_id='TEST_WORKSPACE_B',
            message_id=3,
            slack_ts='2000000001',
            message_text='Secret data for Organization B - Project Beta',
            metadata={
                'workspace_id': 'TEST_WORKSPACE_B',
                'channel_name': 'general',
                'user_id': 'U003'
            }
        )

        chromadb_client.add_message(
            workspace_id='TEST_WORKSPACE_B',
            message_id=4,
            slack_ts='2000000002',
            message_text='Confidential info for Org B - Revenue data',
            metadata={
                'workspace_id': 'TEST_WORKSPACE_B',
                'channel_name': 'general',
                'user_id': 'U004'
            }
        )

        DatabaseConnection.return_connection(conn)

        yield  # Run tests

        # Cleanup after tests
        conn = DatabaseConnection.get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM org_workspaces WHERE workspace_id LIKE 'TEST_%'")
        cur.execute("DELETE FROM message_metadata WHERE workspace_id LIKE 'TEST_%'")
        cur.execute("DELETE FROM workspaces WHERE workspace_id LIKE 'TEST_%'")
        cur.execute("DELETE FROM organizations WHERE org_name LIKE 'Test Org %'")
        conn.commit()
        DatabaseConnection.return_connection(conn)

    def test_chromadb_workspace_isolation(self):
        """
        CRITICAL: Verify ChromaDB searches are filtered by workspace_id.

        Searching Workspace A should NEVER return Workspace B data.
        """
        query_service = QueryService(workspace_id='TEST_WORKSPACE_A')

        # Search for "Organization" - both workspaces have this word
        results = query_service.semantic_search(
            query='Organization',
            n_results=10
        )

        # Verify ALL results are from Workspace A only
        for msg in results:
            workspace_id = msg['metadata']['workspace_id']
            assert workspace_id == 'TEST_WORKSPACE_A', \
                f"SECURITY BREACH: Workspace A query returned Workspace B data! " \
                f"Found workspace_id: {workspace_id}"

        # Verify we got Workspace A data
        assert len(results) > 0, "Should find messages from Workspace A"

        # Verify Workspace B content is NOT in results
        for msg in results:
            text = msg['text'].lower()
            assert 'organization b' not in text, \
                "SECURITY BREACH: Workspace A query returned Org B content!"
            assert 'project beta' not in text, \
                "SECURITY BREACH: Found Workspace B project in Workspace A search!"

    def test_chromadb_reverse_isolation(self):
        """
        CRITICAL: Verify isolation works both ways.

        Searching Workspace B should NEVER return Workspace A data.
        """
        query_service = QueryService(workspace_id='TEST_WORKSPACE_B')

        results = query_service.semantic_search(
            query='Organization',
            n_results=10
        )

        # Verify ALL results are from Workspace B only
        for msg in results:
            workspace_id = msg['metadata']['workspace_id']
            assert workspace_id == 'TEST_WORKSPACE_B', \
                f"SECURITY BREACH: Workspace B query returned Workspace A data! " \
                f"Found workspace_id: {workspace_id}"

        # Verify Workspace A content is NOT in results
        for msg in results:
            text = msg['text'].lower()
            assert 'organization a' not in text, \
                "SECURITY BREACH: Workspace B query returned Org A content!"
            assert 'project alpha' not in text, \
                "SECURITY BREACH: Found Workspace A project in Workspace B search!"

    def test_qa_service_workspace_isolation(self):
        """
        CRITICAL: Verify Q&A service enforces workspace isolation.

        QAService for Workspace A should NEVER access Workspace B data.
        """
        qa_service_a = QAService(workspace_id='TEST_WORKSPACE_A')

        # Ask about "Project" - both workspaces have projects
        result = qa_service_a.answer_question(
            question='What project are we working on?',
            n_context_messages=10
        )

        # Verify answer doesn't contain Workspace B data
        answer = result['answer'].lower()
        assert 'project beta' not in answer, \
            "SECURITY BREACH: QA for Workspace A returned Workspace B project!"
        assert 'organization b' not in answer, \
            "SECURITY BREACH: QA answer leaked Workspace B info!"

        # Verify sources are only from Workspace A
        for source in result.get('sources', []):
            # Check channel matches expected Workspace A channel
            channel = source.get('channel', '')
            assert channel != 'workspace_b_channel', \
                f"SECURITY BREACH: Source from Workspace B in Workspace A results!"

    def test_qa_service_requires_workspace_id(self):
        """
        CRITICAL: QAService must REQUIRE workspace_id.

        Should raise error if workspace_id is None or empty.
        """
        # Test with None
        with pytest.raises((ValueError, TypeError)):
            QAService(workspace_id=None)

        # Test with empty string
        with pytest.raises((ValueError, TypeError)):
            QAService(workspace_id='')

    def test_database_query_isolation(self):
        """
        CRITICAL: Verify PostgreSQL queries are filtered by workspace_id.
        """
        conn = DatabaseConnection.get_connection()
        cur = conn.cursor()

        # Query messages for Workspace A
        cur.execute("""
            SELECT workspace_id, slack_ts, channel_name
            FROM message_metadata
            WHERE workspace_id = 'TEST_WORKSPACE_A'
        """)
        results_a = cur.fetchall()

        # Verify all results are Workspace A
        for row in results_a:
            assert row[0] == 'TEST_WORKSPACE_A', \
                f"SECURITY BREACH: Query for Workspace A returned {row[0]}"

        # Query messages for Workspace B
        cur.execute("""
            SELECT workspace_id, slack_ts, channel_name
            FROM message_metadata
            WHERE workspace_id = 'TEST_WORKSPACE_B'
        """)
        results_b = cur.fetchall()

        # Verify all results are Workspace B
        for row in results_b:
            assert row[0] == 'TEST_WORKSPACE_B', \
                f"SECURITY BREACH: Query for Workspace B returned {row[0]}"

        # Verify results are distinct (no overlap)
        slack_ts_a = {row[1] for row in results_a}
        slack_ts_b = {row[1] for row in results_b}

        assert slack_ts_a.isdisjoint(slack_ts_b), \
            "SECURITY BREACH: Workspace A and B have overlapping message IDs!"

        DatabaseConnection.return_connection(conn)

    def test_org_workspace_relationship(self):
        """
        CRITICAL: Verify org_workspaces table enforces correct relationships.
        """
        conn = DatabaseConnection.get_connection()
        cur = conn.cursor()

        # Get workspaces for Org A
        cur.execute("""
            SELECT workspace_id
            FROM org_workspaces
            WHERE org_id = %s
        """, (self.org_a_id,))
        org_a_workspaces = {row[0] for row in cur.fetchall()}

        assert org_a_workspaces == {'TEST_WORKSPACE_A'}, \
            "Org A should only have Workspace A"

        # Get workspaces for Org B
        cur.execute("""
            SELECT workspace_id
            FROM org_workspaces
            WHERE org_id = %s
        """, (self.org_b_id,))
        org_b_workspaces = {row[0] for row in cur.fetchall()}

        assert org_b_workspaces == {'TEST_WORKSPACE_B'}, \
            "Org B should only have Workspace B"

        # Verify workspaces don't overlap
        assert org_a_workspaces.isdisjoint(org_b_workspaces), \
            "SECURITY BREACH: Organizations share workspaces!"

        DatabaseConnection.return_connection(conn)


class TestAPIWorkspaceAuthorization:
    """
    Test API-level workspace authorization.
    These tests will be implemented once API middleware is built.
    """

    def test_api_rejects_unauthorized_workspace_access(self):
        """
        CRITICAL: API should return 403 when user tries to access
        workspace they don't own.

        TODO: Implement once API middleware is created.
        """
        pytest.skip("API middleware not yet implemented - WEEK 1 TODO")

    def test_api_validates_workspace_in_request(self):
        """
        CRITICAL: API should validate workspace_id in all requests.

        TODO: Implement once API middleware is created.
        """
        pytest.skip("API middleware not yet implemented - WEEK 1 TODO")


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
