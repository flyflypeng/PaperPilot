"""
Organization Name Standardization Tool

Will LLM Various extracted institution name variants are uniformly mapped to standard abbreviations
"""

import json
import os
import re
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple


class InstitutionNormalizer:
    """Organization name normalizer"""

    def __init__(
        self,
        mapping_file: Optional[str] = None,
        custom_mapping_file: Optional[str] = None,
    ):
        """
        Initialize the normalizer

        Args:
            mapping_file: System organization mapping file path, if None then use the default path
            custom_mapping_file: User-defined institution mapping file path (optional)
        """
        if mapping_file is None:
            # Use the default path (in the same directory as this file instituionMap.json）
            current_dir = os.path.dirname(os.path.abspath(__file__))
            mapping_file = os.path.join(current_dir, "instituionMap.json")

        self.mapping_file = mapping_file
        self.custom_mapping_file = custom_mapping_file
        self.institution_map: Dict[str, List[str]] = {}
        self._load_mapping()

        # Build reverse index: full name/Variants -> Standard abbreviation (for fast and exact matching)
        # Use normalized strings as keys
        self._build_reverse_index()

    def _normalize_string(self, text: str) -> str:
        """
        Standardize strings: remove punctuation, unify case, standardize suffix, etc.

        Args:
            text: raw string

        Returns:
            normalized string
        """
        if not text:
            return ""

        # 1. Remove leading and trailing spaces and convert to lowercase
        normalized = text.strip().lower()

        # 2. Remove punctuation (retain spaces and alphanumeric characters)
        # Remove common punctuation: commas, periods, semicolons, colons, etc.
        normalized = re.sub(r'[,.;:!?()\[\]{}"\']+', "", normalized)

        # 3. Standardized common institution suffixes
        # Define suffix mapping table
        suffix_mappings = {
            r"\binc\.?\b": "inc",
            r"\binc,\b": "inc",
            r"\bltd\.?\b": "ltd",
            r"\blimited\b": "ltd",
            r"\bcorp\.?\b": "corp",
            r"\bcorporation\b": "corp",
            r"\blab\.?\b": "lab",
            r"\blaboratory\b": "lab",
            r"\buniv\.?\b": "univ",
            r"\buniversity\b": "univ",
            r"\bcollege\b": "college",
            r"\bschool\b": "school",
            r"\binstitute\b": "inst",
            r"\binstitution\b": "inst",
        }

        for pattern, replacement in suffix_mappings.items():
            normalized = re.sub(pattern, replacement, normalized)

        # 4. Remove excess spaces (merge consecutive spaces into a single space)
        normalized = re.sub(r"\s+", " ", normalized)

        # 5. Remove leading and trailing spaces again
        normalized = normalized.strip()

        return normalized

    def _extract_core_words(self, text: str) -> str:
        """
        Extract core words (remove common suffixes and stop words)

        Args:
            text: normalized string

        Returns:
            core word string
        """
        if not text:
            return ""

        # Common stop words and suffixes
        stop_words = {"the", "of", "and", "at", "in", "on", "for", "to", "a", "an"}
        suffixes = {
            "inc",
            "ltd",
            "corp",
            "lab",
            "univ",
            "college",
            "school",
            "inst",
            "university",
        }

        # Split words
        words = text.split()

        # Filter stop words and suffixes
        core_words = [w for w in words if w not in stop_words and w not in suffixes]

        return " ".join(core_words) if core_words else text

    def _load_mapping(self):
        """Load institution mapping file (system + User-defined)"""
        # Load the system map first
        try:
            with open(self.mapping_file, "r", encoding="utf-8") as f:
                self.institution_map = json.load(f)
            print(
                f"[InstitutionNormalizer] Successfully loaded system map: {len(self.institution_map)} institutions"
            )
        except FileNotFoundError:
            print(
                f"[InstitutionNormalizer] warn: System mapping file does not exist {self.mapping_file}"
            )
            self.institution_map = {}
        except json.JSONDecodeError as e:
            print(f"[InstitutionNormalizer] mistake: System mapping file format error {e}")
            self.institution_map = {}

        # Load user-defined mapping (will overwrite the institution with the same name in the system mapping)
        if self.custom_mapping_file and os.path.exists(self.custom_mapping_file):
            try:
                with open(self.custom_mapping_file, "r", encoding="utf-8") as f:
                    settings = json.load(f)
                    custom_map = settings.get("customInstitutions", {})

                    if custom_map:
                        # Merged into system mapping (user-defined first)
                        self.institution_map.update(custom_map)
                        print(
                            f"[InstitutionNormalizer] Successfully loaded user-defined mapping: {len(custom_map)} institutions"
                        )
            except Exception as e:
                print(f"[InstitutionNormalizer] Failed to load user-defined mapping: {e}")

    def _build_reverse_index(self):
        """
        Build an inverted index for fast and accurate matching
        Use standardized strings as keys to improve matching success rate
        """
        self.reverse_index: Dict[str, str] = {}
        self.normalized_index: Dict[str, str] = {}  # Standardized index
        self.core_words_index: Dict[str, str] = {}  # Core word index

        for standard_name, variants in self.institution_map.items():
            # 1. Original lowercase index (maintains backward compatibility)
            self.reverse_index[standard_name.lower()] = standard_name
            for variant in variants:
                self.reverse_index[variant.lower()] = standard_name

            # 2. Standardized index (remove punctuation, standardized suffix)
            normalized_standard = self._normalize_string(standard_name)
            if normalized_standard:
                self.normalized_index[normalized_standard] = standard_name

            for variant in variants:
                normalized_variant = self._normalize_string(variant)
                if normalized_variant:
                    self.normalized_index[normalized_variant] = standard_name

            # 3. Core word index (for partial matching)
            core_standard = self._extract_core_words(normalized_standard)
            if core_standard:
                # If the standard name is not already in the core word index, add it
                if core_standard not in self.core_words_index:
                    self.core_words_index[core_standard] = standard_name
                # If there are multiple variants mapped to the same core word, keep the first one (usually the standard name)

            for variant in variants:
                normalized_variant = self._normalize_string(variant)
                core_variant = self._extract_core_words(normalized_variant)
                if core_variant and core_variant not in self.core_words_index:
                    self.core_words_index[core_variant] = standard_name

    def _calculate_similarity(self, str1: str, str2: str) -> float:
        """
        Calculate the similarity of two strings (0-1）

        use SequenceMatcher Calculate similarity and consider multiple matching strategies
        """
        s1_lower = str1.lower().strip()
        s2_lower = str2.lower().strip()

        # 1. exactly the same
        if s1_lower == s2_lower:
            return 1.0

        # 2. One contains the other (the shorter one is completely inside the longer one)
        if s1_lower in s2_lower or s2_lower in s1_lower:
            shorter = min(len(s1_lower), len(s2_lower))
            longer = max(len(s1_lower), len(s2_lower))
            # If the shorter length accounts for the longer 70% Above, it is considered that the similarity is high
            if shorter / longer > 0.7:
                return 0.88

        # 3. use SequenceMatcher Calculate sequence similarity
        ratio = SequenceMatcher(None, s1_lower, s2_lower).ratio()

        # 4. If the similarity is low but contains the same keywords, you can improve some scores
        # Extract words
        words1 = set(s1_lower.split())
        words2 = set(s2_lower.split())
        common_words = words1 & words2

        # If there are long words in common (>3characters) to improve similarity
        if common_words:
            long_common_words = [w for w in common_words if len(w) > 3]
            if long_common_words:
                # The amount of improvement depends on the proportion of common words
                word_overlap = len(common_words) / max(len(words1), len(words2))
                ratio = max(ratio, 0.7 * word_overlap + 0.3 * ratio)

        return ratio

    def _fuzzy_match(
        self, extracted_name: str, threshold: float = 0.85
    ) -> Optional[str]:
        """
        Fuzzy matching organization name

        Args:
            extracted_name: LLM Extracted organization name
            threshold: Similarity threshold (default 0.80）

        Returns:
            The standard abbreviation matched, or returned if there is no match None
        """
        best_match = None
        best_score = threshold

        # Iterate over all standard names and their variations
        for standard_name, variants in self.institution_map.items():
            # Check the standard name itself
            score = self._calculate_similarity(extracted_name, standard_name)
            if score > best_score:
                best_score = score
                best_match = standard_name

            # Check all variations
            for variant in variants:
                score = self._calculate_similarity(extracted_name, variant)
                if score > best_score:
                    best_score = score
                    best_match = standard_name

        return best_match

    def normalize(
        self, extracted_name: str, fuzzy: bool = True, threshold: float = 0.85
    ) -> str:
        """
        Standardized organization name (using hierarchical matching strategy)

        Args:
            extracted_name: LLM Extracted organization name
            fuzzy: Whether to use fuzzy matching (default True）
            threshold: Similarity threshold for fuzzy matching (default 0.85）

        Returns:
            Standardized organization abbreviation (if no match is found, the original name is returned)
        """
        if not extracted_name or not extracted_name.strip():
            return extracted_name

        name = extracted_name.strip()
        name_lower = name.lower()

        # ===== First level: exact match (original lowercase) =====
        exact_match = self.reverse_index.get(name_lower)
        if exact_match:
            return exact_match

        # ===== Second level: exact matching after standardization =====
        normalized_name = self._normalize_string(name)
        if normalized_name:
            normalized_match = self.normalized_index.get(normalized_name)
            if normalized_match:
                print(
                    f"[InstitutionNormalizer] normalized matching: '{name}' -> '{normalized_match}'"
                )
                return normalized_match

        # ===== The third level: core word matching =====
        core_words = self._extract_core_words(normalized_name)
        if core_words:
            # Check if the core words match exactly
            core_match = self.core_words_index.get(core_words)
            if core_match:
                print(f"[InstitutionNormalizer] core word matching: '{name}' -> '{core_match}'")
                return core_match

            # Check the inclusion relationship: whether the core word is included in the core word of a certain configuration, or vice versa
            for config_core, standard_name in self.core_words_index.items():
                # If the extracted core word contains the configured core word, or the configured core word contains the extracted core word
                if core_words in config_core or config_core in core_words:
                    # Further check: make sure it's not a too short match (to avoid false matches)
                    min_length = min(len(core_words), len(config_core))
                    if min_length >= 3:  # At least3characters
                        print(
                            f"[InstitutionNormalizer] core words contain matches: '{name}' -> '{standard_name}'"
                        )
                        return standard_name

        # ===== Level 4: Fuzzy matching (if enabled) =====
        if fuzzy:
            fuzzy_match = self._fuzzy_match(name, threshold)
            if fuzzy_match:
                print(f"[InstitutionNormalizer] fuzzy matching: '{name}' -> '{fuzzy_match}'")
                return fuzzy_match

        # ===== Unable to match, return original name =====
        return name

    def normalize_list(
        self,
        extracted_names: List[str],
        fuzzy: bool = True,
        threshold: float = 0.85,
        deduplicate: bool = True,
    ) -> List[str]:
        """
        List of names of batch standardization organizations

        Args:
            extracted_names: LLM Extracted list of organization names
            fuzzy: Whether to use fuzzy matching
            threshold: Similarity threshold for fuzzy matching
            deduplicate: Whether to remove duplicates (default True）

        Returns:
            Standardized list of institutional abbreviations
        """
        normalized = []
        seen = set()

        for name in extracted_names:
            standard_name = self.normalize(name, fuzzy=fuzzy, threshold=threshold)

            if deduplicate:
                # Deduplication: If the standardized name already exists, skip it
                if standard_name.lower() not in seen:
                    seen.add(standard_name.lower())
                    normalized.append(standard_name)
            else:
                normalized.append(standard_name)

        return normalized

    def get_statistics(self) -> Dict[str, int]:
        """
        Get mapping statistics

        Returns:
            Dictionary containing statistics
        """
        total_variants = sum(
            len(variants) for variants in self.institution_map.values()
        )
        return {
            "total_institutions": len(self.institution_map),
            "total_variants": total_variants,
            "average_variants_per_institution": (
                total_variants / len(self.institution_map)
                if self.institution_map
                else 0
            ),
        }


# Create a global singleton instance
_normalizer_instance: Optional[InstitutionNormalizer] = None


def get_normalizer() -> InstitutionNormalizer:
    """Get the global normalizer instance (singleton mode)"""
    global _normalizer_instance
    if _normalizer_instance is None:
        _normalizer_instance = InstitutionNormalizer()
    return _normalizer_instance


def normalize_institution(extracted_name: str) -> str:
    """
    Standardize individual institution names (convenience function)

    Args:
        extracted_name: LLM Extracted organization name

    Returns:
        Standardized organization abbreviation
    """
    normalizer = get_normalizer()
    return normalizer.normalize(extracted_name)


def normalize_institutions(extracted_names: List[str]) -> List[str]:
    """
    List of standardization body names (convenience function)

    Args:
        extracted_names: LLM Extracted list of organization names

    Returns:
        Standardized list of institutional abbreviations
    """
    normalizer = get_normalizer()
    return normalizer.normalize_list(extracted_names)


if __name__ == "__main__":
    # test code
    normalizer = InstitutionNormalizer()

    # Print statistics
    stats = normalizer.get_statistics()
    print("\n=== Institutional Mapping Statistics ===")
    print(f"Number of standard institutions: {stats['total_institutions']}")
    print(f"Total number of variants: {stats['total_variants']}")
    print(f"Average number of variants per institution: {stats['average_variants_per_institution']:.2f}")

    # test case
    test_cases = [
        "Tsinghua University",
        "THU",
        "Massachusetts Institute of Technology",
        "MIT",
        "Google Brain",
        "Google Research",
        "Fudan University",
        "The University of Hong Kong",
        "HKU",
        "University of California Berkeley",
        "Berkeley",
        "Cal",
        "Random University",  # non-existent organization
        "Tsing hua",  # Typos (fuzzy match test)
    ]

    print("\n=== standardized testing ===")
    for test_name in test_cases:
        normalized = normalizer.normalize(test_name)
        # Check if the match is successful (via reverse index or fuzzy match)
        exact_match = normalizer.reverse_index.get(test_name.lower())
        if exact_match:
            # exact match
            print(f"✓ {test_name:40s} -> {normalized} (accurate)")
        elif normalized != test_name:
            # fuzzy matching
            print(f"✓ {test_name:40s} -> {normalized} (Vague)")
        else:
            # No match
            print(f"✗ {test_name:40s} -> (No match)")

    # Test batch standardization
    print("\n=== Batch standardized testing ===")
    test_list = [
        "Tsinghua University",
        "THU",  # should be deduplicated
        "Peking University",
        "PKU",  # should be deduplicated
        "MIT",
        "Stanford University",
    ]
    normalized_list = normalizer.normalize_list(test_list, deduplicate=True)
    print(f"enter: {test_list}")
    print(f"output: {normalized_list}")
