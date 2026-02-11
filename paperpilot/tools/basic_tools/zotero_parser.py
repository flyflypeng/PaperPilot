"""
Zotero RDF file parser
used to parse from Zotero Exported RDF file and converted to project Paper Format
"""

import html
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add the project root directory to Python path so that it can be imported core module
_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

try:
    from rdflib import RDF, RDFS, Graph, Literal, Namespace
    from rdflib.namespace import DC, DCTERMS, FOAF
except ImportError:
    print("Requires installation rdflib: pip install rdflib")
    raise

from paperpilot.core.base_paper import Paper

# Define namespace
Z = Namespace("http://www.zotero.org/namespaces/export#")
BIB = Namespace("http://purl.org/net/biblio#")
VCARD = Namespace("http://nwalsh.com/rdf/vCard#")
LINK = Namespace("http://purl.org/rss/1.0/modules/link/")


class ZoteroRDFParser:
    """parse Zotero RDF file parser"""

    def __init__(self, rdf_file_path: str):
        """
        Initialize the parser

        Args:
            rdf_file_path: RDF file path
        """
        self.rdf_file_path = Path(rdf_file_path)
        self.graph = Graph()
        self.papers: List[Paper] = []
        self.memos: Dict[str, str] = {}  # Store note information
        self.attachments: Dict[str, List[Dict[str, str]]] = {}  # Store attachment information
        self.collections: Dict[str, Dict[str, Any]] = (
            {}
        )  # storage Collection information {collection_id: {title, children, papers}}
        self.paper_to_collections: Dict[str, List[str]] = (
            {}
        )  # Save papers to Collection mapping {paper_id: [collection_paths]}
        self.paper_subjects: Dict[str, str] = (
            {}
        )  # Store the original of the paper subject {paper_id: original_subject}

    def _fix_rdf_errors(self):
        """repair RDF Common format errors in files"""
        import re

        fixed_file = self.rdf_file_path.parent / f"{self.rdf_file_path.stem}_fixed.rdf"

        # If the repair file already exists, use it directly
        if fixed_file.exists():
            return

        try:
            # Read original file
            with open(self.rdf_file_path, "rb") as f:
                content = f.read().decode("utf-8", errors="ignore")

            # fix invalid rdf:resource element
            content = re.sub(r'<rdf:resource rdf:resource="[^"]+"/>', "", content)

            # Save the repaired file
            with open(fixed_file, "w", encoding="utf-8") as f:
                f.write(content)

            print(f"Repaired file created: {fixed_file}")
        except Exception as e:
            print(f"An error occurred while repairing the file: {e}")

    def parse(self) -> List[Paper]:
        """
        parse RDF file and return Paper list

        Returns:
            Paper object list
        """
        print(f"Parsing RDF document: {self.rdf_file_path}")

        # Try fixing common ones first RDF Format error
        self._fix_rdf_errors()

        # load RDF document
        try:
            self.graph.parse(str(self.rdf_file_path), format="xml")
        except Exception as e:
            print(f"Parse error: {e}")
            print("Try using the repaired file...")
            # If parsing fails, try using the fixed version
            fixed_file = (
                self.rdf_file_path.parent / f"{self.rdf_file_path.stem}_fixed.rdf"
            )
            if fixed_file.exists():
                self.graph.parse(str(fixed_file), format="xml")
            else:
                raise

        # Parse notes and attachments first
        self._parse_memos()
        self._parse_attachments()

        # parse Collection Hierarchy
        self._parse_collections()

        # Parsing essay items
        self._parse_papers()

        # Assign a paper Collection path
        self._assign_collections_to_papers()

        print(f"Analysis completed, total found {len(self.papers)} papers")
        return self.papers

    def _parse_memos(self):
        """Parse remark information"""
        for memo_subj, memo_pred, memo_obj in self.graph.triples(
            (None, RDF.type, BIB.Memo)
        ):
            memo_id = str(memo_subj)
            # Get the note content
            for _, _, value in self.graph.triples((memo_subj, RDF.value, None)):
                memo_text = str(value)
                # Remove HTML Label
                memo_text = re.sub(r"<[^>]+>", "", memo_text)
                memo_text = html.unescape(memo_text).strip()
                self.memos[memo_id] = memo_text

    def _parse_attachments(self):
        """Parse attachment information"""
        for attach_subj, attach_pred, attach_obj in self.graph.triples(
            (None, RDF.type, Z.Attachment)
        ):
            attach_id = str(attach_subj)

            # Get attachment title
            title = ""
            for _, _, title_obj in self.graph.triples((attach_subj, DC.title, None)):
                title = str(title_obj)

            # Get attachment type
            attach_type = ""
            for _, _, type_obj in self.graph.triples((attach_subj, LINK.type, None)):
                attach_type = str(type_obj)

            # Find papers citing this attachment
            for paper_subj, _, _ in self.graph.triples((None, LINK.link, attach_subj)):
                paper_id = str(paper_subj)
                if paper_id not in self.attachments:
                    self.attachments[paper_id] = []
                self.attachments[paper_id].append(
                    {"title": title, "type": attach_type, "id": attach_id}
                )

    def _normalize_collection_id(self, coll_id: str) -> str:
        """Standardize Collection ID,extract #collection_XX part"""
        if "#collection_" in coll_id:
            return "#" + coll_id.split("#")[-1]
        return coll_id

    def _parse_collections(self):
        """parse Collection Hierarchy"""
        # First collect all Collection basic information
        for coll_subj, _, _ in self.graph.triples((None, RDF.type, Z.Collection)):
            coll_id_raw = str(coll_subj)
            coll_id = self._normalize_collection_id(coll_id_raw)

            # get Collection title
            title = ""
            for _, _, title_obj in self.graph.triples((coll_subj, DC.title, None)):
                title = str(title_obj).strip()

            if not title:
                continue  # Skip those without titles Collection

            # initialization Collection information
            if coll_id not in self.collections:
                self.collections[coll_id] = {
                    "title": title,
                    "children": [],  # child Collection IDs
                    "papers": [],  # Papers included directly IDs
                    "raw_id": coll_id_raw,  # save original ID for matching
                }

            # get hasPart relation
            for _, _, part_obj in self.graph.triples(
                (coll_subj, DCTERMS.hasPart, None)
            ):
                part_id_raw = str(part_obj)
                part_id = self._normalize_collection_id(part_id_raw)

                # Judgment is the son Collection Or a paper
                # If with #collection_ At the beginning, it’s Zi Collection
                if part_id.startswith("#collection_"):
                    if part_id not in self.collections[coll_id]["children"]:
                        self.collections[coll_id]["children"].append(part_id)
                else:
                    # Otherwise a thesis (probably URI or item ID）
                    if part_id_raw not in self.collections[coll_id]["papers"]:
                        self.collections[coll_id]["papers"].append(part_id_raw)

        print(f"parse to {len(self.collections)} indivual Collection")

    def _build_collection_path(self, collection_id: str, visited: set = None) -> str:
        """
        build Collection full path to

        Args:
            collection_id: Collection ID
            visited: visited Collection(Prevent loops)

        Returns:
            Collection The full path, such as "Diffusion/Auto Regressive"
        """
        if visited is None:
            visited = set()

        if collection_id in visited:
            return ""  # Prevent loops

        if collection_id not in self.collections:
            return ""

        visited.add(collection_id)
        title = self.collections[collection_id]["title"]

        # Find parent Collection
        parent_id = None
        for coll_id, coll_info in self.collections.items():
            if collection_id in coll_info["children"]:
                parent_id = coll_id
                break

        if parent_id:
            parent_path = self._build_collection_path(parent_id, visited)
            if parent_path:
                return f"{parent_path}/{title}"
            else:
                return title
        else:
            return title

    def _assign_collections_to_papers(self):
        """Assigned to each paper Collection path"""
        # Structuring thesis ID arrive Paper Object mapping
        paper_map = {}
        for paper in self.papers:
            # try many possibilities ID Format
            possible_ids = [paper.id]
            # from paper_subjects Original found in subject
            for orig_id, orig_subj in self.paper_subjects.items():
                if paper.id in orig_id or orig_id.replace(":", "_") == paper.id:
                    possible_ids.append(orig_subj)
                    possible_ids.append(orig_id)
                    # If the original ID Include urn:isbn, adding both original and converted formats
                    if "urn:isbn:" in orig_id:
                        # Add original format
                        possible_ids.append(orig_id)
                        # Add converted format if not already available
                        converted_id = orig_id.replace("urn:", "").replace(":", "_")
                        if converted_id not in possible_ids:
                            possible_ids.append(converted_id)
                    break
            # Add to URL
            if "url" in paper.extra:
                possible_ids.append(paper.extra["url"])

            # deal with ISBN Format: if paper.id yes isbn_xxx, also add urn:isbn:xxx Format
            if paper.id.startswith("isbn_"):
                isbn_number = paper.id.replace("isbn_", "")
                possible_ids.append(f"urn:isbn:{isbn_number}")
                possible_ids.append(f"isbn:{isbn_number}")

            for pid in possible_ids:
                paper_map[pid] = paper

        # For each paper find all the Collection
        for coll_id, coll_info in self.collections.items():
            category_path = self._build_collection_path(coll_id)
            if not category_path:
                continue

            # check this Collection All paper citations included
            for paper_ref in coll_info["papers"]:
                # Try to match the paper
                matched_paper = None

                # direct match
                if paper_ref in paper_map:
                    matched_paper = paper_map[paper_ref]
                else:
                    # Try a partial match (handle URI format differences)
                    for paper_id, paper in paper_map.items():
                        # Check various matching methods
                        if (
                            paper_ref == paper_id
                            or paper_ref.endswith(paper_id)
                            or paper_id.endswith(paper_ref)
                            or paper_ref in paper_id
                            or paper_id in paper_ref
                        ):
                            # Stricter matching: check if it is the same resource
                            if "arxiv.org" in paper_ref and "arxiv.org" in paper_id:
                                matched_paper = paper
                                break
                            elif "http" in paper_ref and "http" in paper_id:
                                # Extract path parts for comparison
                                ref_path = paper_ref.split("/")[-1]
                                id_path = paper_id.split("/")[-1]
                                if (
                                    ref_path == id_path
                                    or ref_path in id_path
                                    or id_path in ref_path
                                ):
                                    matched_paper = paper
                                    break
                            elif "#item_" in paper_ref or "#item_" in paper_id:
                                # extract item ID
                                ref_item = (
                                    paper_ref.split("#item_")[-1]
                                    if "#item_" in paper_ref
                                    else ""
                                )
                                id_item = (
                                    paper_id.split("#item_")[-1]
                                    if "#item_" in paper_id
                                    else ""
                                )
                                if ref_item and id_item and ref_item == id_item:
                                    matched_paper = paper
                                    break
                            elif "urn:isbn:" in paper_ref or "isbn_" in paper_id:
                                # deal with ISBN Format:urn:isbn:xxx and isbn_xxx match
                                # extract ISBN Number part
                                ref_isbn = ""
                                if "urn:isbn:" in paper_ref:
                                    ref_isbn = (
                                        paper_ref.split("urn:isbn:")[-1]
                                        .split("/")[0]
                                        .split("%")[0]
                                        .strip()
                                    )
                                elif "isbn:" in paper_ref:
                                    ref_isbn = (
                                        paper_ref.split("isbn:")[-1]
                                        .split("/")[0]
                                        .split("%")[0]
                                        .strip()
                                    )

                                id_isbn = ""
                                if paper_id.startswith("isbn_"):
                                    id_isbn = paper_id.replace("isbn_", "").strip()
                                elif "isbn" in paper_id.lower():
                                    # Try to extract from other formats ISBN
                                    import re

                                    isbn_match = re.search(r"[\d-]+", paper_id)
                                    if isbn_match:
                                        id_isbn = isbn_match.group(0)

                                if ref_isbn and id_isbn:
                                    # standardization ISBN(Remove hyphens for comparison)
                                    ref_isbn_normalized = ref_isbn.replace(
                                        "-", ""
                                    ).replace(" ", "")
                                    id_isbn_normalized = id_isbn.replace(
                                        "-", ""
                                    ).replace(" ", "")
                                    if (
                                        ref_isbn_normalized == id_isbn_normalized
                                        or ref_isbn in id_isbn
                                        or id_isbn in ref_isbn
                                    ):
                                        matched_paper = paper
                                        break

                if matched_paper:
                    # Add to category to paper
                    if "category" not in matched_paper.extra:
                        matched_paper.extra["category"] = []
                    elif isinstance(matched_paper.extra["category"], str):
                        matched_paper.extra["category"] = [
                            matched_paper.extra["category"]
                        ]

                    if category_path not in matched_paper.extra["category"]:
                        matched_paper.extra["category"].append(category_path)

        # Will category Convert list to string and remove redundant paths
        for paper in self.papers:
            if "category" in paper.extra:
                if isinstance(paper.extra["category"], list):
                    categories = paper.extra["category"]
                    # Remove redundant paths: If one path is a prefix of another path, remove the prefix path
                    # Keep only the longest (most specific) paths
                    filtered_categories = []
                    for cat_path in categories:
                        # Check if this path is a prefix of other paths
                        is_prefix = False
                        for other_path in categories:
                            if cat_path != other_path and other_path.startswith(
                                cat_path + "/"
                            ):
                                is_prefix = True
                                break
                        if not is_prefix:
                            filtered_categories.append(cat_path)

                    # If there are multiple paths after filtering, sort by length (longest first)
                    filtered_categories.sort(key=len, reverse=True)

                    category_str = "; ".join(filtered_categories)
                    paper.extra["category"] = category_str
                    # also added to subject field (if empty)
                    if not paper.subject and category_str:
                        paper.subject = (
                            filtered_categories[0] if filtered_categories else ""
                        )

    def _parse_papers(self):
        """Parsing essay items"""
        # Find all paper descriptions
        paper_descriptions = set()

        # Find all rdf:Description node
        for subj, pred, obj in self.graph.triples((None, RDF.type, None)):
            if isinstance(subj, str) or hasattr(subj, "toPython"):
                paper_descriptions.add(subj)

        # Find all itemType Items (papers, journal articles, etc.)
        for subj, pred, obj in self.graph.triples((None, Z.itemType, None)):
            item_type = str(obj).lower()
            # Only process article-related entry types (including preprint）
            if item_type in [
                "conferencepaper",
                "journalarticle",
                "article",
                "book",
                "booksection",
                "preprint",
            ]:
                paper = self._parse_single_paper(subj)
                if paper:
                    self.papers.append(paper)

    def _parse_single_paper(self, paper_subj) -> Optional[Paper]:
        """Parse a single paper entry"""
        paper_id = str(paper_subj)

        # Save the original copy of the paper subject(for matching Collection）
        self.paper_subjects[paper_id] = paper_id

        # create Paper object
        paper = Paper()
        paper.id = paper_id.replace("urn:", "").replace(":", "_")

        # parse title
        for _, _, title_obj in self.graph.triples((paper_subj, DC.title, None)):
            paper.title = str(title_obj).strip()

        # Analyze the author
        authors_list = []
        seen_authors = set()  # Used to remove duplicates
        for _, _, authors_seq in self.graph.triples((paper_subj, BIB.authors, None)):
            # RDF Sequence usage rdf:_1, rdf:_2 etc. to represent sequence items
            # Iterate over all possible sequence indices (up to100authors)
            from rdflib import URIRef

            for i in range(1, 101):  # Most supported100authors
                rdf_index = URIRef(f"http://www.w3.org/1999/02/22-rdf-syntax-ns#_{i}")
                author_persons = list(self.graph.objects(authors_seq, rdf_index))
                if not author_persons:
                    break  # No more authors

                for author_person in author_persons:
                    surname = ""
                    given_name = ""
                    for _, _, surname_obj in self.graph.triples(
                        (author_person, FOAF.surname, None)
                    ):
                        surname = str(surname_obj)
                    for _, _, given_obj in self.graph.triples(
                        (author_person, FOAF.givenName, None)
                    ):
                        given_name = str(given_obj)
                    if surname or given_name:
                        author_name = f"{given_name} {surname}".strip()
                        # Use author name to remove duplicates
                        if author_name and author_name not in seen_authors:
                            authors_list.append(author_name)
                            seen_authors.add(author_name)

        if authors_list:
            paper.authors = ", ".join(authors_list)

        # parse summary
        for _, _, abstract_obj in self.graph.triples(
            (paper_subj, DCTERMS.abstract, None)
        ):
            paper.abstract = str(abstract_obj).strip()

        # parse date
        for _, _, date_obj in self.graph.triples((paper_subj, DC.date, None)):
            date_str = str(date_obj)
            # Try to extract the year
            year_match = re.search(r"(\d{4})", date_str)
            if year_match:
                paper.year = year_match.group(1)

        # Analyze journals/Meeting
        for _, _, journal_obj in self.graph.triples(
            (paper_subj, DCTERMS.isPartOf, None)
        ):
            for _, _, journal_title in self.graph.triples(
                (journal_obj, DC.title, None)
            ):
                paper.journal = str(journal_title).strip()
                break

        # Parse meeting information
        for _, _, conf_obj in self.graph.triples((paper_subj, BIB.presentedAt, None)):
            for _, _, conf_title in self.graph.triples((conf_obj, DC.title, None)):
                if not paper.journal:
                    paper.journal = str(conf_title).strip()
                break

        # parse publisher
        publisher_list = []
        for _, _, publisher_obj in self.graph.triples((paper_subj, DC.publisher, None)):
            for _, _, org_name in self.graph.triples((publisher_obj, FOAF.name, None)):
                publisher_list.append(str(org_name))
        if publisher_list:
            paper.affiliation = ", ".join(publisher_list)

        # Parse identifier (DOI, URLwait)
        for _, _, identifier_obj in self.graph.triples(
            (paper_subj, DC.identifier, None)
        ):
            identifier_str = str(identifier_obj)
            if identifier_str.startswith("DOI"):
                paper.extra["doi"] = identifier_str.replace("DOI", "").strip()
            elif identifier_str.startswith("ISBN"):
                paper.extra["isbn"] = identifier_str.replace("ISBN", "").strip()
            elif isinstance(identifier_obj, str):
                # may be URI
                if "http" in identifier_str:
                    paper.extra["url"] = identifier_str

        # parse URI
        for _, _, uri_obj in self.graph.triples((paper_subj, DC.identifier, None)):
            for _, _, uri_value in self.graph.triples((uri_obj, RDF.value, None)):
                uri_str = str(uri_value)
                if uri_str.startswith("http"):
                    paper.extra["url"] = uri_str

        # Parse page number
        for _, _, pages_obj in self.graph.triples((paper_subj, BIB.pages, None)):
            paper.extra["pages"] = str(pages_obj)

        # parse language
        for _, _, lang_obj in self.graph.triples((paper_subj, Z.libraryCatalog, None)):
            paper.extra["library_catalog"] = str(lang_obj)

        # Parse commit date
        for _, _, date_submitted in self.graph.triples(
            (paper_subj, DCTERMS.dateSubmitted, None)
        ):
            paper.upload_date = str(date_submitted).strip()

        # Parsing notes
        for _, _, memo_ref in self.graph.triples(
            (paper_subj, DCTERMS.isReferencedBy, None)
        ):
            memo_id = str(memo_ref)
            if memo_id in self.memos:
                paper.notes = self.memos[memo_id]

        # Parse attachments
        if paper_id in self.attachments:
            attachments = self.attachments[paper_id]
            # Find PDF appendix
            for attach in attachments:
                if attach["type"] == "application/pdf":
                    paper.extra["pdf_attachment"] = attach["title"]
                    break

        # Parse entry type
        for _, _, item_type in self.graph.triples((paper_subj, Z.itemType, None)):
            paper.extra["item_type"] = str(item_type)

        # If there is no title, skip this entry
        if not paper.title:
            return None

        return paper

    def export_to_json(self, output_file: Optional[str] = None) -> str:
        """
        Export the parsing results as JSON document

        Args:
            output_file: Output file path, if None is automatically generated

        Returns:
            Output file path
        """
        import json

        if output_file is None:
            output_file = str(
                self.rdf_file_path.parent / f"{self.rdf_file_path.stem}_parsed.json"
            )

        papers_data = Paper.to_dict_list(self.papers)

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(papers_data, f, ensure_ascii=False, indent=2)

        print(f"Exported {len(papers_data)} papers arrive: {output_file}")
        return output_file

    def print_summary(self):
        """Print summary of parsing results"""
        print("\n" + "=" * 60)
        print("Summary of parsing results")
        print("=" * 60)
        print(f"Total number of papers: {len(self.papers)}")

        # Statistics titled papers
        with_title = sum(1 for p in self.papers if p.title)
        print(f"titled paper: {with_title}")

        # Statistics papers with authors
        with_authors = sum(1 for p in self.papers if p.authors)
        print(f"Papers with authors: {with_authors}")

        # Statistics papers with abstracts
        with_abstract = sum(1 for p in self.papers if p.abstract)
        print(f"Papers with abstracts: {with_abstract}")

        # Statistics papers with notes
        with_notes = sum(1 for p in self.papers if p.notes)
        print(f"Papers with notes: {with_notes}")

        # Statistics classified papers
        with_category = sum(1 for p in self.papers if "category" in p.extra)
        print(f"Classified papers: {with_category}")

        # show Collection statistics
        print(f"\nCollection statistics:")
        print(f"total Collection number: {len(self.collections)}")
        collections_with_children = sum(
            1 for c in self.collections.values() if c["children"]
        )
        print(f"With subdirectories Collection: {collections_with_children}")

        # before showing5Titles of papers
        print("\nforward5papers:")
        for i, paper in enumerate(self.papers[:5], 1):
            print(
                f"{i}. {paper.title[:60]}..."
                if len(paper.title) > 60
                else f"{i}. {paper.title}"
            )
            if paper.authors:
                print(f"   author: {paper.authors[:50]}...")
            if paper.year:
                print(f"   years: {paper.year}")


def main():
    """Main function, used for command line calls"""
    import sys

    rdf_file = "My library.rdf"
    if len(sys.argv) > 1:
        rdf_file = sys.argv[1]

    parser = ZoteroRDFParser(rdf_file)
    papers = parser.parse()
    parser.print_summary()

    # Export as JSON
    output_file = parser.export_to_json()
    print(f"\nThe parsing results have been saved to: {output_file}")


if __name__ == "__main__":
    main()
