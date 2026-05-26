# -*- coding: utf-8 -*-
import os
import re
import hashlib
import zipfile

PAGES_URL = "https://addonniss.github.io/repository.addonniss/zips"
REPO_ID = "repository.addonniss"
ADDON_ZIP_RETENTION_COUNT = 5


def get_version(xml_path):
    """Extract x.y.z version from addon.xml"""
    try:
        with open(xml_path, "r", encoding="utf-8") as f:
            content = f.read()
        match = re.search(r'version=["\']([0-9]+\.[0-9]+\.[0-9]+)["\']', content)
        if match:
            return match.group(1)
    except Exception as e:
        print(f"Error reading version from {xml_path}: {e}")

    raise ValueError(f"Cannot find proper x.y.z version in {xml_path}")


def version_key(filename):
    match = re.search(r'(\d+)\.(\d+)\.(\d+)', filename)
    if match:
        return tuple(int(x) for x in match.groups())
    return (0, 0, 0)


def find_addon_dirs():
    """
    Return addon directories in repo root that contain addon.xml,
    excluding the repository root addon.xml itself.
    """
    addon_dirs = []

    for entry in os.listdir("."):
        if not os.path.isdir(entry):
            continue
        if entry.startswith(".") or entry == "zips":
            continue

        xml_path = os.path.join(entry, "addon.xml")
        if os.path.exists(xml_path):
            addon_dirs.append(entry)

    return sorted(addon_dirs)


def read_addon_xml_without_declaration(xml_path):
    with open(xml_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    if lines and lines[0].lstrip().startswith("<?xml"):
        return "".join(lines[1:]).strip() + "\n"
    return "".join(lines).strip() + "\n"


def rewrite_repo_addon_xml_for_pages(repo_xml_text):
    return (
        repo_xml_text
        .replace(
            "https://raw.githubusercontent.com/Addonniss/repository.addonniss/main/zips/addons.xml",
            f"{PAGES_URL}/addons.xml"
        )
        .replace(
            "https://raw.githubusercontent.com/Addonniss/repository.addonniss/main/zips/addons.xml.md5",
            f"{PAGES_URL}/addons.xml.md5"
        )
        .replace(
            "https://raw.githubusercontent.com/Addonniss/repository.addonniss/main/zips/",
            f"{PAGES_URL}/"
        )
    )


def zip_addon_folder(addon_id, version, zips_path):
    target_dir = os.path.join(zips_path, addon_id)
    os.makedirs(target_dir, exist_ok=True)

    zip_name = f"{addon_id}-{version}.zip"
    zip_path = os.path.join(target_dir, zip_name)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(addon_id):
            for file in files:
                fp = os.path.join(root, file)
                arcname = os.path.join(addon_id, os.path.relpath(fp, addon_id))
                z.write(fp, arcname)

    print(f"Created addon zip: {zip_path}")
    prune_old_addon_zips(addon_id, target_dir)


def prune_old_addon_zips(addon_id, target_dir):
    if addon_id == REPO_ID:
        return

    zip_files = [f for f in os.listdir(target_dir) if f.endswith(".zip")]
    zip_files = sorted(zip_files, key=version_key, reverse=True)

    for old_zip in zip_files[ADDON_ZIP_RETENTION_COUNT:]:
        old_zip_path = os.path.join(target_dir, old_zip)
        try:
            os.remove(old_zip_path)
            print(f"Removed old addon zip: {old_zip_path}")
        except Exception as e:
            print(f"Warning: failed to remove old zip {old_zip_path}: {e}")


def zip_repository_addon(version, zips_path):
    target_dir = os.path.join(zips_path, REPO_ID)
    os.makedirs(target_dir, exist_ok=True)

    zip_name = f"{REPO_ID}-{version}.zip"
    zip_path = os.path.join(target_dir, zip_name)

    with open("addon.xml", "r", encoding="utf-8") as f:
        repo_xml = f.read()

    repo_xml = rewrite_repo_addon_xml_for_pages(repo_xml)

    temp_xml_path = os.path.join(target_dir, "addon.xml")
    with open(temp_xml_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(repo_xml)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(temp_xml_path, os.path.join(REPO_ID, "addon.xml"))
        if os.path.exists("icon.png"):
            z.write("icon.png", os.path.join(REPO_ID, "icon.png"))
        if os.path.exists("fanart.jpg"):
            z.write("fanart.jpg", os.path.join(REPO_ID, "fanart.jpg"))

    print(f"Created repository zip: {zip_path}")

    # cleanup temp rewritten xml
    try:
        os.remove(temp_xml_path)
    except Exception:
        pass

    # create index.html pointing to newest repo zip
    zip_files = [f for f in os.listdir(target_dir) if f.endswith(".zip")]
    if zip_files:
        newest_zip = sorted(zip_files, key=version_key, reverse=True)[0]
        index_path = os.path.join(target_dir, "index.html")
        with open(index_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Addonniss Repository</title>
</head>
<body>
    <h1>Addonniss Repository</h1>
    <a href="{newest_zip}">{newest_zip}</a>
</body>
</html>
""")
        print(f"Created index.html pointing to newest zip: {newest_zip}")


def create_repo():
    zips_path = "zips"
    os.makedirs(zips_path, exist_ok=True)

    addon_dirs = find_addon_dirs()
    print("Detected addon folders:", addon_dirs)

    xml_content = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<addons>\n'

    # normal addons from subfolders
    for addon_id in addon_dirs:
        xml_path = os.path.join(addon_id, "addon.xml")

        if not os.path.exists(xml_path):
            print(f"Warning: {xml_path} not found, skipping")
            continue

        version = get_version(xml_path)
        print(f"Found version {version} for {addon_id}")

        xml_content += read_addon_xml_without_declaration(xml_path)
        zip_addon_folder(addon_id, version, zips_path)

    # repository addon from root addon.xml
    repo_xml_path = "addon.xml"
    if os.path.exists(repo_xml_path):
        repo_version = get_version(repo_xml_path)
        print(f"Found version {repo_version} for {REPO_ID}")

        xml_content += read_addon_xml_without_declaration(repo_xml_path)
        zip_repository_addon(repo_version, zips_path)
    else:
        print("Warning: root addon.xml not found, skipping repository addon")

    xml_content += "</addons>\n"

    addons_xml_path = os.path.join(zips_path, "addons.xml")
    with open(addons_xml_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(xml_content)

    md5 = hashlib.md5(xml_content.encode("utf-8")).hexdigest()
    with open(os.path.join(zips_path, "addons.xml.md5"), "w", encoding="utf-8", newline="\n") as f:
        f.write(md5.strip())

    print("Repository generation complete.")
    print("Generated files:")
    for root, _, files in os.walk(zips_path):
        for file in files:
            print("-", os.path.join(root, file))


if __name__ == "__main__":
    create_repo()
