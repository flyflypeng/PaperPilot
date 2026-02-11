"""
Custom organization mapping management routing
"""

import json
import os

from flask import jsonify, request


def register_institution_mapping_routes(app, daily_arxiv_settings_file: str):
    """
    Register Custom Organization Mapping Management Route

    Args:
        app: Flask Application examples
        daily_arxiv_settings_file: Daily arXiv Set file path
    """

    def load_settings():
        """Load settings file"""
        if os.path.exists(daily_arxiv_settings_file):
            with open(daily_arxiv_settings_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def save_settings(settings):
        """Save settings file"""
        with open(daily_arxiv_settings_file, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)

    @app.route("/api/custom-institutions", methods=["GET"])
    def get_custom_institutions():
        """Get user-defined institution mapping"""
        try:
            settings = load_settings()
            custom_institutions = settings.get("customInstitutions", {})

            # Convert to the format required by the front end
            result = []
            for abbr, variants in custom_institutions.items():
                result.append({"abbreviation": abbr, "variants": variants})

            # Sort by abbreviation
            result.sort(key=lambda x: x["abbreviation"])

            return jsonify(
                {"success": True, "institutions": result, "total": len(result)}
            )
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/api/all-known-institutions", methods=["GET"])
    def get_all_known_institutions():
        """Get all known institutions (system default + User-defined)"""
        try:
            import sys

            tools_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "tools"
            )
            if tools_dir not in sys.path:
                sys.path.insert(0, tools_dir)

            from institution_normalizer import InstitutionNormalizer

            # Create a normalizer instance (will load the system mapping + User-defined mapping)
            normalizer = InstitutionNormalizer(
                custom_mapping_file=daily_arxiv_settings_file
            )

            # Get all standards body names (key）
            all_abbrs = list(normalizer.institution_map.keys())

            return jsonify(
                {"success": True, "institutions": all_abbrs, "total": len(all_abbrs)}
            )
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/api/custom-institutions", methods=["POST"])
    def save_custom_institution():
        """Save or update a single custom institution"""
        try:
            data = request.json
            abbreviation = data.get("abbreviation", "").strip()
            variants = data.get("variants", [])

            if not abbreviation:
                return jsonify({"success": False, "error": "Abbreviation cannot be empty"}), 400

            # Remove duplicates and filter out null values
            unique_variants = []
            seen = set()
            for v in variants:
                v_clean = v.strip()
                if v_clean and v_clean not in seen:
                    seen.add(v_clean)
                    unique_variants.append(v_clean)

            if not unique_variants:
                return jsonify({"success": False, "error": "At least one full name variant is required"}), 400

            # Load settings
            settings = load_settings()
            if "customInstitutions" not in settings:
                settings["customInstitutions"] = {}

            # depositary institution
            settings["customInstitutions"][abbreviation] = unique_variants
            save_settings(settings)

            # Reload normalizer
            reload_normalizer()

            return jsonify({"success": True, "message": f"mechanism {abbreviation} saved"})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/api/custom-institutions/<abbreviation>", methods=["DELETE"])
    def delete_custom_institution(abbreviation):
        """Delete custom organization"""
        try:
            settings = load_settings()
            custom_institutions = settings.get("customInstitutions", {})

            if abbreviation in custom_institutions:
                del custom_institutions[abbreviation]
                settings["customInstitutions"] = custom_institutions
                save_settings(settings)
                reload_normalizer()

                return jsonify(
                    {"success": True, "message": f"Organization deleted {abbreviation}"}
                )
            else:
                return jsonify({"success": False, "error": "Organization does not exist"}), 404
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    def reload_normalizer():
        """Reload normalizer"""
        try:
            import sys

            tools_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "tools"
            )
            if tools_dir not in sys.path:
                sys.path.insert(0, tools_dir)

            # Force reimport of normalizer module
            import importlib

            import institution_normalizer

            importlib.reload(institution_normalizer)

            print("[CustomInstitution] Normalizer reloaded")
        except Exception as e:
            print(f"[CustomInstitution] Reloading normalizer failed: {e}")
