import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parent
ADDON_LANGUAGES = ROOT / "service.translatarr" / "languages.py"
EXTRACTOR_APP = ROOT / "translatarr-remote-extractor" / "app.py"


def load_assignments(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    assignments = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    try:
                        assignments[target.id] = ast.literal_eval(node.value)
                    except Exception:
                        continue
    return assignments


def build_lang_name_to_iso(languages_dict):
    result = {}
    for _, value in languages_dict.items():
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            continue
        name, iso = value
        result[name] = iso
    return result


def main():
    addon_values = load_assignments(ADDON_LANGUAGES)
    extractor_values = load_assignments(EXTRACTOR_APP)

    addon_lang_name_to_iso = build_lang_name_to_iso(addon_values["LANGUAGES"])
    addon_iso_variants = addon_values["ISO_VARIANTS"]

    extractor_lang_name_to_iso = extractor_values["LANG_NAME_TO_ISO"]
    extractor_iso_variants = extractor_values["ISO_VARIANTS"]

    mismatches = []

    if addon_lang_name_to_iso != extractor_lang_name_to_iso:
        mismatches.append("LANG_NAME_TO_ISO mismatch")

    if addon_iso_variants != extractor_iso_variants:
        mismatches.append("ISO_VARIANTS mismatch")

    if mismatches:
        raise SystemExit(
            "Translatarr language sync check failed: {0}".format(", ".join(mismatches))
        )

    print("Translatarr language sync OK")


if __name__ == "__main__":
    main()
