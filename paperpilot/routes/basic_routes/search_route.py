from __future__ import annotations

from typing import Dict, Optional, Protocol

from flask import Flask, jsonify, request

from paperpilot.core.search_index import SearchIndex


class GetCategoriesFn(Protocol):
    def __call__(self) -> Dict[str, any]: ...


class GetCategoryPathFn(Protocol):
    def __call__(
        self,
        categories: Dict[str, any],
        category_id: str,
        path: Optional[list[str]] = None,
    ) -> Optional[list[str]]: ...


def register_search_routes(
    app: Flask,
    *,
    get_categories: GetCategoriesFn,
    get_category_path: GetCategoryPathFn,
    upload_folder: str,
    search_index: SearchIndex,
) -> None:
    @app.route("/api/search")
    def api_search():
        """
        search title/authors/abstract. Supports global or limited categories.
        use SQLite FTS5 Full-text search, performance greatly improved.
        """
        query = (request.args.get("q") or "").strip()
        if not query:
            return jsonify({"results": []})

        # Limit on the number of results obtained (default 100）
        limit = int(request.args.get("limit", 100))

        # Get categoryID(optional)
        category_id = (request.args.get("category_id") or "").strip() or None

        # Use database search
        try:
            results = search_index.search(
                query=query,
                category_id=category_id,
                limit=limit,
            )

            # Sort by number of matching fields and similarity (database has been sorted by rank Sorting, do secondary sorting here)
            results.sort(
                key=lambda r: (
                    -len(r.get("matched_fields", [])),  # Those with more matching fields are given priority.
                    -r.get("similarity", 0.0),  # Those with higher similarity will be given priority.
                    r.get("title") or "",  # Title alphabetical order
                )
            )

            return jsonify({"results": results})
        except Exception as e:
            print(f"Search failed: {e}")
            import traceback

            traceback.print_exc()
            return jsonify({"results": [], "error": str(e)})
