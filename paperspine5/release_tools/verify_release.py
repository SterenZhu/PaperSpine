#!/usr/bin/env python3
"""Verify the public PaperSpine5 prerelease metadata and local source contract."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()
def main()->int:
    manifest=json.loads((ROOT/"website"/"downloads"/"manifest.json").read_text(encoding="utf-8"))
    assert manifest["product"]=="PaperSpine5"
    assert manifest["tag"]=="v"+manifest["version"]
    assert manifest["repository"]=="https://github.com/SterenZhu/PaperSpine"
    assert {x["kind"] for x in manifest["artifacts"]} == {
        "suite"
    }
    assert len(manifest["artifacts"]) == 1
    assert manifest["artifacts"][0]["platform"] == "windows-amd64"
    assert manifest == json.loads((ROOT/"release"/manifest["tag"]/"manifest.json").read_text(encoding="utf-8"))
    installer = ROOT/"install.ps1"
    assert installer.stat().st_size == manifest["release_assets"]["installer_bytes"]
    assert sha256(installer) == manifest["release_assets"]["installer_sha256"]
    channel = json.loads((ROOT/"website/downloads/update-channel.json").read_text(encoding="utf-8"))
    assert channel["product_version"] == manifest["version"]
    assert set(channel["bundles"]) == {"windows-amd64"}
    bundle = channel["bundles"]["windows-amd64"]
    item = manifest["artifacts"][0]
    assert channel["bundle"] == bundle
    for key in ("sha256", "bytes", "build_id", "platform"):
        assert bundle[key] == item[key]
    assert bundle["url"] == item["download_url"]
    assert bundle["product_version"] == manifest["version"]
    assert channel == json.loads((ROOT/"website/downloads/update-channel-windows-amd64.json").read_text(encoding="utf-8"))
    checksum=(ROOT/"website"/"downloads"/"checksums.sha256").read_text(encoding="ascii")
    for item in manifest["artifacts"]:
        assert len(item["sha256"])==64 and item["bytes"]>0
        assert item["sha256"] in checksum and item["file"] in checksum
        assert item["download_url"].startswith("https://github.com/SterenZhu/PaperSpine/releases/download/")
    for path in [ROOT/"product-release.json",ROOT/"website"/"downloads"/"manifest.json",ROOT/"release"/manifest["tag"]/"manifest.json"]:
        text=path.read_text(encoding="utf-8")
        for forbidden in ("M:\\项目","C:\\Users\\Wubin","work_carbon_submission"): assert forbidden not in text
    print(json.dumps({"status":"PASS","version":manifest["version"],"artifacts":len(manifest["artifacts"]),"suite_bytes":next(x["bytes"] for x in manifest["artifacts"] if x["kind"]=="suite")},ensure_ascii=False))
    return 0
if __name__=="__main__": raise SystemExit(main())
