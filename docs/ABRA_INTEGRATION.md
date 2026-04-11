# Abra Integration — How Amebo Uses abra-lib

## Current State

Amebo duplicates abra's data access logic in `binding_repo.py`. This works
but means query improvements must be ported between repos.

## Target State

Amebo installs `abra-lib` from PyPI and subclasses `AbraStore` for its
multi-tenant, project-doc-boosted needs. Core query logic lives in one place.

```
pip install abra-lib
```

## What Changes in Amebo

### binding_repo.py → thin wrapper

**Before** (current): 421 lines of SQL that mirrors abra's pgvector impl.

**After**: ~60 lines that subclass AbraStore.

```python
from abra import AbraStore, SearchResult
from src.db.abra_connection import AbraConnection
from src.db.connection import DatabaseConnection
from src.db.embedding import embed_text


class AmeboStore(AbraStore):
    """
    Amebo's abra store — adds project doc boosting and dual-DB fallback.
    """

    def rank_results(self, results, query):
        """Boost project docs over contact stubs."""
        project = [r for r in results if self._is_project_doc(r)]
        other = [r for r in results if not self._is_project_doc(r)]
        return project + other

    def _is_project_doc(self, result):
        sf = result.content.source_file or ""
        return any(sf.startswith(p) for p in (
            "projects/", "Ideas/", "plans/", "cli-"
        ))


def get_store(org_id=None):
    """
    Factory: returns an AbraStore configured for amebo's environment.

    - org_id=None: read from shared abra DB (team-wide knowledge)
    - org_id=N: read from local amebo tables (instance-isolated)
    """
    if org_id is None and AbraConnection.is_available():
        return AmeboStore(
            get_conn=AbraConnection.get_connection,
            put_conn=AbraConnection.return_connection,
            embed_fn=embed_text,
        )
    else:
        DatabaseConnection.initialize_pool()
        return AmeboStore(
            get_conn=DatabaseConnection.get_connection,
            put_conn=DatabaseConnection.return_connection,
            embed_fn=embed_text,
            org_id=org_id,
            table_prefix="abra_",
        )
```

### binding_service.py → uses AbraStore API

The service layer stays — it provides higher-level operations like
`about()`, `enrich_names()`, `format_for_prompt()`. But instead of
calling `self.repo.search_bindings_by_name(...)` with raw SQL, it calls
`self.store.bindings_for(...)` which returns typed `Binding` objects.

### Tool registry → gets store in context

The tool `execute()` context dict gains a `store` key:

```python
context = {
    "workspace_id": workspace_id,
    "org_id": org_id,
    "store": get_store(org_id),   # <-- any tool can use abra
}
```

Any tool that wants to resolve names, check hot tags, or look up
relationships just does `context["store"].bindings_for("peter")`.

## What Stays the Same

- `abra_connection.py` — still manages the read-only pool to abra's DB
- `schema.sql` — local `abra_*` tables unchanged (for org-isolated data)
- `embed_text()` — amebo's embedding function, injected into AbraStore
- The abra database itself — no schema changes needed

## Migration Steps (on server)

1. `pip install abra-lib` (or install from local: `pip install -e /opt/shared/repos/abra/lib`)
2. Create `AmeboStore` class (as shown above)
3. Update `binding_service.py` to use `AmeboStore` instead of `BindingRepo`
4. Update `tools/registry.py` to pass store in context
5. Delete `binding_repo.py` (all its logic now lives in abra-lib)
6. Test: verify `about()`, `enrich_names()`, `search_content()` still work

## Override Points

| What | How | When |
|------|-----|------|
| Search ranking | Override `rank_results()` | Amebo boosts project docs |
| PII rules | Pass custom `PiiChecker` | Different jurisdictions |
| Connection mgmt | Inject `get_conn`/`put_conn` | Pool vs raw connection |
| Table names | Set `table_prefix` | Local tables vs shared |
| Embeddings | Inject `embed_fn` | Different models/hosts |
| Multi-tenancy | Set `org_id` | Instance isolation |

## What Abra Gets Back

When amebo improves query logic (better similarity thresholds, smarter
search), it can be contributed upstream to `AbraStore.search_content()`
so all consumers benefit. Amebo-specific logic stays in `AmeboStore`.
