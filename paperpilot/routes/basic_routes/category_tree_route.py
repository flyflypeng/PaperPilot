from __future__ import annotations

import os
import shutil
import uuid
from io import BytesIO
from typing import Any, Callable, Dict, List, Optional, Protocol

from flask import Flask, jsonify, request, send_file


class GetCategoriesFn(Protocol):
    def __call__(self) -> Dict[str, Any]: ...


class SaveCategoriesFn(Protocol):
    def __call__(self, categories: Dict[str, Any]) -> None: ...


class FindCategoryNodeFn(Protocol):
    def __call__(
        self, categories: Dict[str, Any], category_id: str
    ) -> Optional[Dict[str, Any]]: ...


class GetCategoryPathFn(Protocol):
    def __call__(
        self,
        categories: Dict[str, Any],
        category_id: str,
        path: Optional[List[str]] = None,
    ) -> Optional[List[str]]: ...


class GetPapersInCategoryFn(Protocol):
    def __call__(self, category_id: str, category_path: List[str]) -> List[Any]: ...


class AddPdfCountsFn(Protocol):
    def __call__(
        self, categories: Dict[str, Any], count_func: Callable[[str], int]
    ) -> Dict[str, Any]: ...


class GetCategoryPdfCountFn(Protocol):
    def __call__(
        self,
        categories: Dict[str, Any],
        category_id: str,
        get_papers_in_category: GetPapersInCategoryFn,
    ) -> int: ...


class PaperStore(Protocol):
    def list_by_category(self, category_id: str) -> List[Any]: ...
    def remove(self, paper_id: str) -> Optional[Any]: ...


def register_category_routes(
    app: Flask,
    *,
    get_categories: GetCategoriesFn,
    save_categories: SaveCategoriesFn,
    find_category_node: FindCategoryNodeFn,
    get_category_path: GetCategoryPathFn,
    get_papers_in_category: GetPapersInCategoryFn,
    add_pdf_counts_to_categories: AddPdfCountsFn,
    get_category_pdf_count: GetCategoryPdfCountFn,
    paper_store: PaperStore,
    upload_folder: str,
) -> None:
    @app.route("/api/categories")
    def api_categories():
        categories = get_categories()
        categories_with_counts = add_pdf_counts_to_categories(
            categories,
            lambda cid: get_category_pdf_count(categories, cid, get_papers_in_category),
        )
        return jsonify(categories_with_counts)

    @app.route("/api/categories", methods=["POST"])
    def api_add_category():
        data = request.json or {}
        parent_id = data.get("parent_id")
        name = data.get("name")

        if not name:
            return (
                jsonify({"success": False, "error": "Category name is required"}),
                400,
            )

        categories = get_categories()
        if not parent_id or parent_id in {"root", categories.get("id")}:
            parent_node = categories
        else:
            parent_node = find_category_node(categories, parent_id)

        if parent_node is None:
            return (
                jsonify({"success": False, "error": "Parent category not found"}),
                404,
            )

        new_category = {"id": str(uuid.uuid4()), "name": name, "children": []}
        parent_node.setdefault("children", []).append(new_category)
        save_categories(categories)
        return jsonify({"success": True, "category": new_category})

    @app.route("/api/categories/<category_id>", methods=["PUT"])
    def api_rename_category(category_id):
        data = request.json or {}
        new_name = data.get("name")

        if not new_name:
            return (
                jsonify({"success": False, "error": "Category name is required"}),
                400,
            )

        categories = get_categories()
        category_node = find_category_node(categories, category_id)

        if category_node is None:
            return jsonify({"success": False, "error": "Category not found"}), 404

        category_node["name"] = new_name
        save_categories(categories)
        return jsonify({"success": True})

    @app.route("/api/categories/<category_id>/pin", methods=["PUT"])
    def api_pin_category(category_id):
        """Pin to top/Cancel pinned category"""
        data = request.json or {}
        pinned = data.get("pinned", False)

        categories = get_categories()
        category_node = find_category_node(categories, category_id)

        if category_node is None:
            return jsonify({"success": False, "error": "Category not found"}), 404

        category_node["pinned"] = pinned
        save_categories(categories)
        return jsonify({"success": True, "pinned": pinned})

    @app.route("/api/categories/<category_id>/color", methods=["PUT"])
    def api_change_category_color(category_id):
        """Change category icon color"""
        data = request.json or {}
        color = data.get("color")

        if not color:
            return (
                jsonify({"success": False, "error": "Color is required"}),
                400,
            )

        categories = get_categories()
        category_node = find_category_node(categories, category_id)

        if category_node is None:
            return jsonify({"success": False, "error": "Category not found"}), 404

        category_node["iconColor"] = color
        save_categories(categories)
        return jsonify({"success": True, "color": color})

    @app.route("/api/categories/<category_id>", methods=["DELETE"])
    def api_delete_category(category_id):
        categories = get_categories()

        def collect_all_category_ids(node: Dict[str, Any]) -> List[str]:
            """Recursively collect a category and all its subcategories ID"""
            ids = [node.get("id")]
            for child in node.get("children", []):
                ids.extend(collect_all_category_ids(child))
            return ids

        def delete_papers_in_categories(category_ids: List[str]) -> int:
            """from paper_store Delete all papers under the specified category"""
            deleted_count = 0
            for cat_id in category_ids:
                papers = paper_store.list_by_category(cat_id)
                for paper in papers:
                    paper_id = paper.id if hasattr(paper, "id") else paper.get("id")
                    if paper_id:
                        paper_store.remove(paper_id)
                        deleted_count += 1
            return deleted_count

        def delete_category_recursive(node: Dict[str, Any], target_id: str) -> bool:
            children = node.get("children", [])
            for index, child in enumerate(children):
                if child["id"] == target_id:
                    # 1. Collect all categories to be deleted ID(Includes subcategories)
                    all_category_ids = collect_all_category_ids(child)

                    # 2. from paper_store Delete all related papers from
                    deleted_papers = delete_papers_in_categories(all_category_ids)
                    print(f"Already from paper_store delete {deleted_papers} papers")

                    # 3. Delete physical folder
                    category_path = get_category_path(categories, target_id)
                    if category_path and len(category_path) > 1:
                        folder_path = os.path.join(upload_folder, *category_path[1:])
                        if os.path.exists(folder_path):
                            shutil.rmtree(folder_path)
                            print(f"Category folder deleted: {folder_path}")

                    # 4. Remove node from classification tree
                    del children[index]
                    return True
                if delete_category_recursive(child, target_id):
                    return True
            return False

        if delete_category_recursive(categories, category_id):
            save_categories(categories)
            return jsonify({"success": True})

        return jsonify({"success": False, "error": "Category not found"}), 404

    @app.route("/api/categories/<category_id>/move", methods=["PUT"])
    def api_move_category(category_id):
        """
        Move category to new parent category

        Request body:
        {
            "target_parent_id": "target parent categoryID" or "root" Indicates moving to the root directory
        }
        """
        data = request.json or {}
        target_parent_id = data.get("target_parent_id")

        if not target_parent_id:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "target parent categoryIDcannot be empty",
                    }
                ),
                400,
            )

        categories = get_categories()

        # Cannot move root category
        if category_id == categories.get("id") or category_id == "root":
            return (
                jsonify({"success": False, "error": "Cannot move root category"}),
                400,
            )

        # cannot move to self
        if category_id == target_parent_id:
            return (
                jsonify(
                    {"success": False, "error": "Category cannot be moved to itself"}
                ),
                400,
            )

        # Check if you are trying to move a category to its subcategory (which will cause a loop)
        def is_descendant(
            node: Dict[str, Any], ancestor_id: str, target_id: str
        ) -> bool:
            """examine target_id whether it is ancestor_id descendant nodes of"""
            if node.get("id") == ancestor_id:
                # Ancestor node found, now check target_id Is it in its subtree
                def find_in_subtree(n: Dict[str, Any]) -> bool:
                    if n.get("id") == target_id:
                        return True
                    for child in n.get("children", []):
                        if find_in_subtree(child):
                            return True
                    return False

                return find_in_subtree(node)

            for child in node.get("children", []):
                if is_descendant(child, ancestor_id, target_id):
                    return True
            return False

        if is_descendant(categories, category_id, target_parent_id):
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Categories cannot be moved to their subcategories",
                    }
                ),
                400,
            )

        # Get the original path (for moving folders)
        old_path = get_category_path(categories, category_id)

        # Find and remove classification nodes
        category_node = None

        def remove_from_parent(node: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            children = node.get("children", [])
            for index, child in enumerate(children):
                if child["id"] == category_id:
                    return children.pop(index)
                result = remove_from_parent(child)
                if result:
                    return result
            return None

        category_node = remove_from_parent(categories)

        if not category_node:
            return jsonify({"success": False, "error": "Category does not exist"}), 404

        # Find the target parent node and add a category
        if target_parent_id in {"root", categories.get("id")}:
            target_parent = categories
        else:
            target_parent = find_category_node(categories, target_parent_id)

        if not target_parent:
            # Restore original state
            # To simplify the process here, it should actually be restored to its original position.
            return (
                jsonify(
                    {"success": False, "error": "Target parent category does not exist"}
                ),
                404,
            )

        target_parent.setdefault("children", []).append(category_node)

        # Get new path
        new_path = get_category_path(categories, category_id)

        # Move physical folder
        if old_path and new_path and len(old_path) > 1 and len(new_path) > 1:
            old_folder = os.path.join(upload_folder, *old_path[1:])
            new_folder = os.path.join(upload_folder, *new_path[1:])

            if os.path.exists(old_folder) and old_folder != new_folder:
                # Make sure the parent directory of the new path exists
                new_parent_folder = os.path.dirname(new_folder)
                os.makedirs(new_parent_folder, exist_ok=True)

                # If a folder with the same name already exists in the target location, it needs to be processed
                if os.path.exists(new_folder):
                    print(
                        f"[mobile classification] The folder already exists in the target location: {new_folder}"
                    )
                    # Optionally merge or return an error
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": "A folder with the same name already exists in the target location",
                            }
                        ),
                        400,
                    )

                try:
                    shutil.move(old_folder, new_folder)
                    print(
                        f"[mobile classification] Folder moved: {old_folder} -> {new_folder}"
                    )
                except Exception as e:
                    print(f"[mobile classification] Failed to move folder: {e}")
                    # Continue saving category structures even if folder move fails

        save_categories(categories)

        return jsonify(
            {
                "success": True,
                "category": category_node,
                "old_path": old_path,
                "new_path": new_path,
            }
        )

    @app.route("/api/categories/<category_id>/export-bibtex", methods=["GET"])
    def api_export_category_bibtex(category_id: str):
        """
        Export all papers under a category and all its subcategories BibTeX

        Recursively traverse the classification tree and collect all papers BibTeX, merged into one .bib document
        """
        try:
            categories = get_categories()
            category_node = find_category_node(categories, category_id)

            if not category_node:
                return jsonify({"error": "Category not found"}), 404

            # Recursively collect all papers BibTeX
            def collect_papers_recursive(node: Dict[str, Any]) -> List[Any]:
                """Recursively collect all papers under a category and its subcategories"""
                papers = []

                # Get papers in the current category
                node_path = get_category_path(categories, node["id"])
                if node_path:
                    node_papers = get_papers_in_category(node["id"], node_path)
                    papers.extend(node_papers)

                # Recursively process subcategories
                for child in node.get("children", []):
                    papers.extend(collect_papers_recursive(child))

                return papers

            all_papers = collect_papers_recursive(category_node)

            if not all_papers:
                return jsonify({"error": "There are no papers in this category"}), 404

            # collect all BibTeX
            bibtex_entries = []
            for paper in all_papers:
                # paper may be Paper object or dictionary
                if hasattr(paper, "bibtex"):
                    bibtex = paper.bibtex
                elif isinstance(paper, dict):
                    bibtex = paper.get("bibtex", "")
                else:
                    bibtex = ""

                if bibtex and bibtex.strip():
                    bibtex_entries.append(bibtex.strip())

            if not bibtex_entries:
                return (
                    jsonify({"error": "There are no papers in this category BibTeX"}),
                    404,
                )

            # merge all BibTeX entry
            bibtex_content = "\n\n".join(bibtex_entries)

            # Generate file names (using category names)
            category_name = category_node.get("name", "export")
            # Clean file names (remove special characters)
            safe_name = "".join(
                c if c.isalnum() or c in (" ", "-", "_") else "" for c in category_name
            )
            safe_name = safe_name.strip().replace(" ", "_")
            filename = f"{safe_name}_bibtex.bib"

            # Create file object
            bibtex_bytes = bibtex_content.encode("utf-8")
            bibtex_file = BytesIO(bibtex_bytes)

            print(
                f"[Export BibTeX] Classification: {category_name}, Number of papers: {len(all_papers)}, BibTeX Number of entries: {len(bibtex_entries)}"
            )

            return send_file(
                bibtex_file,
                mimetype="application/x-bibtex",
                as_attachment=True,
                download_name=filename,
            )

        except Exception as exc:
            print(f"Export BibTeX fail: {exc}")
            import traceback

            traceback.print_exc()
            return jsonify({"error": f"Export failed: {str(exc)}"}), 500

    @app.route("/api/categories/<category_id>/copy-arxiv-urls", methods=["GET"])
    def api_copy_category_arxiv_urls(category_id: str):
        """
        Error 500 (Server Error)!!1500.That’s an error.There was an error. Please try again later.That’s all we know. arXiv URL

        Return format:title：URL，title：URL
        """
        try:
            categories = get_categories()
            category_node = find_category_node(categories, category_id)

            if not category_node:
                return jsonify({"error": "Category not found"}), 404

            # Collect all papers recursively
            def collect_papers_recursive(node: Dict[str, Any]) -> List[Any]:
                """Recursively collect all papers under a category and its subcategories"""
                papers = []

                # Get papers in the current category
                node_path = get_category_path(categories, node["id"])
                if node_path:
                    node_papers = get_papers_in_category(node["id"], node_path)
                    papers.extend(node_papers)

                # Recursively process subcategories
                for child in node.get("children", []):
                    papers.extend(collect_papers_recursive(child))

                return papers

            all_papers = collect_papers_recursive(category_node)

            if not all_papers:
                return jsonify({"error": "There are no papers in this category"}), 404

            # collect all there are arXiv URL thesis
            arxiv_entries = []
            for paper in all_papers:
                # paper may be Paper object or dictionary
                arxiv_url = None
                arxiv_id = None
                title = ""

                if hasattr(paper, "arxiv_url"):
                    arxiv_url = paper.arxiv_url
                    arxiv_id = getattr(paper, "arxiv_id", None)
                    title = paper.title or paper.filename or ""
                elif isinstance(paper, dict):
                    arxiv_url = paper.get("arxiv_url")
                    arxiv_id = paper.get("arxiv_id")
                    title = paper.get("title") or paper.get("filename") or ""
                else:
                    continue

                # if not arxiv_url But there is arxiv_id,according to arxiv_id build URL
                if not arxiv_url or not arxiv_url.strip():
                    if arxiv_id and arxiv_id.strip():
                        arxiv_url = f"https://arxiv.org/abs/{arxiv_id.strip()}"
                    else:
                        continue  # Neither arxiv_url Neither arxiv_id,jump over

                # Processed with arXiv URL thesis
                if arxiv_url and arxiv_url.strip():
                    arxiv_entries.append(
                        {
                            "title": title.strip() if title else "Untitled paper",
                            "url": arxiv_url.strip(),
                        }
                    )

            if not arxiv_entries:
                return (
                    jsonify(
                        {"error": "There are no papers in this category arXiv URL"}
                    ),
                    404,
                )

            # formatted as "title：URL\n\ntitle：URL" Format (separate different papers with two newlines)
            formatted_text = "\n\n".join(
                [f"{entry['title']}：{entry['url']}" for entry in arxiv_entries]
            )

            print(
                f"[copy arXiv URL] Classification: {category_node.get('name', 'export')}, Total number of papers: {len(all_papers)}, have arXiv URL number of papers: {len(arxiv_entries)}"
            )
            if len(all_papers) > len(arxiv_entries):
                skipped_count = len(all_papers) - len(arxiv_entries)
                print(
                    f"[copy arXiv URL] warn: skipped {skipped_count} No articles arXiv URL/ID thesis"
                )

            return jsonify(
                {"success": True, "text": formatted_text, "count": len(arxiv_entries)}
            )

        except Exception as exc:
            print(f"get arXiv URL fail: {exc}")
            import traceback

            traceback.print_exc()
            return jsonify({"error": str(exc)}), 500
