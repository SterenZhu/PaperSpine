"""Same-task output directory preferences and public artifact/milestone sync."""
from __future__ import annotations

import hashlib
import json
import re
import sys
import uuid
from pathlib import Path, PurePosixPath, PureWindowsPath

STAGES = ("intake", "research", "contribution", "evidence", "draft", "figure", "review", "delivery")
TYPES = ("research_note", "evidence_graph", "manuscript_source", "figure", "pdf", "docx",
         "tex", "bibliography", "review_packet")


class CommandFailure(RuntimeError):
    def __init__(self, error):
        super().__init__(json.dumps(error, ensure_ascii=False))
        self.error = error


def binding_file(profile, task_id):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", task_id):
        raise ValueError("Invalid task ID")
    # Task IDs may contain ':'; use a Windows-safe filename.
    return profile / "host-output-bindings" / (hashlib.sha256(task_id.encode()).hexdigest() + ".json")


def output_directory(profile, task_id, binding):
    """Read a host preference; task stage/configuration remain server facts."""
    path = binding_file(profile, task_id)
    if not path.is_file():
        return None
    state = json.loads(path.read_text(encoding="utf-8-sig"))
    identity = {key: binding[key] for key in ("user_data_root", "domain_database")}
    if state.get("task_id") != task_id or state.get("binding") != identity:
        raise ValueError("Output directory belongs to a different task store")
    return state["writing_directory"]


class Checkpoint:
    def __init__(self, profile, task_id, binding, rpc):
        self.profile, self.task_id, self.binding, self.rpc = profile.resolve(), task_id, binding, rpc
        sys.path.insert(0, str(Path(binding["project_root"]) / "03_联合开发/src"))
        from paperspine_figure_integration.filesystem_paths import native_path, resolve_path
        self.native = native_path
        self.resolve = resolve_path
        self.path = binding_file(self.profile, task_id)
        self.identity = {key: binding[key] for key in ("user_data_root", "domain_database")}
        self.completed = []

    def snapshot(self):
        view = self.rpc("paperspine_get_task", {"task_id": self.task_id})
        if view.get("task_id") != self.task_id or type(view.get("task_version")) is not int:
            raise ValueError("Snapshot does not identify the same task and current version")
        return view

    def load(self):
        state = json.loads(self.native(self.path).read_text(encoding="utf-8-sig"))
        if state.get("task_id") != self.task_id or state.get("binding") != self.identity:
            raise ValueError("Output directory belongs to a different task store")
        return state

    def save(self, state):
        self.native(self.path.parent).mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + "." + uuid.uuid4().hex + ".tmp")
        try:
            self.native(temporary).write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            self.native(temporary).replace(self.native(self.path))
        finally:
            self.native(temporary).unlink(missing_ok=True)

    def bind(self, directory):
        self.snapshot()  # Do not create a preference for an unknown task.
        root = self.resolve(directory, strict=True)
        if not self.native(root).is_dir():
            raise ValueError("Writing directory must already exist")
        if any(root.is_relative_to(Path(self.binding[key]).resolve())
               for key in ("user_data_root", "core_root", "project_root")):
            raise ValueError("Choose an external writing directory, outside task data and product files")
        previous = self.load() if self.native(self.path).is_file() else {}
        if previous.get("pending"):
            raise ValueError("An output sync has an unresolved command; resume checkpoint before rebinding")
        state = {"task_id": self.task_id, "binding": self.identity, "writing_directory": str(root),
                 "grant_id": "host-output-" + hashlib.sha256(str(root).encode()).hexdigest()[:24],
                 "published": previous.get("published", {}) if previous.get("writing_directory") == str(root) else {}}
        self.save(state)
        return {"status": "BOUND", "task_id": self.task_id, "writing_directory": str(root),
                "task_state_changed": False}

    def command(self, tool, view, payload):
        arguments = {"request": {
            "schema_version": "1.1", "task_id": self.task_id,
            "command_id": "host-checkpoint-" + uuid.uuid4().hex,
            "expected_version": view["task_version"], "payload": payload}}
        self.state["pending"] = {"tool": tool, "arguments": arguments}
        self.save(self.state)
        return self.finish_pending()

    def finish_pending(self):
        pending = self.state["pending"]
        try:
            result = self.rpc(pending["tool"], pending["arguments"])
        except CommandFailure as exc:
            if exc.error.get("code") in ("version_conflict", "validation_failed", "forbidden", "not_found"):
                del self.state["pending"]
                self.save(self.state)
            raise
        if result.get("result_type") != "completed":
            raise ValueError("Public command did not complete; read the same task before retrying")
        view = self.snapshot()
        del self.state["pending"]
        self.save(self.state)
        return view

    def sync(self, manifest):
        state = self.load()
        self.state = state
        if state.get("pending"):
            # An explicit rerun replays the exact saved command, never a new
            # write after a missing acknowledgement.
            self.finish_pending()
        stage, summary, files = manifest.get("stage"), manifest.get("summary"), manifest.get("files")
        if stage not in STAGES or not isinstance(summary, str) or not summary.strip():
            raise ValueError("Checkpoint requires an explicit real stage and nonempty factual summary")
        if not isinstance(files, list) or not files:
            raise ValueError("Checkpoint requires an explicit nonempty file list")
        root = self.resolve(state["writing_directory"], strict=True)
        entries, seen = [], set()
        # Validate and hash every requested file before submitting any write.
        for item in files:
            relative, kind = item.get("path"), item.get("artifact_type")
            if not isinstance(relative, str) or kind not in TYPES:
                raise ValueError("Each file requires path and a supported artifact_type")
            value = PurePosixPath(relative)
            if (not relative or value.is_absolute() or PureWindowsPath(relative).drive or ":" in relative
                    or "\\" in relative or ".." in value.parts or value.as_posix() != relative):
                raise ValueError("File path must be a plain writing-directory-relative path")
            if relative in seen:
                raise ValueError("Duplicate file path in checkpoint")
            seen.add(relative)
            path = root / relative
            # Preserve the product's link/reparse and containment policy.
            from paperspine_figure_integration.p7_artifact_import import MAX_SOURCE_BYTES, checked_path
            checked_path(path)
            if not self.resolve(path, strict=True).is_relative_to(root):
                raise ValueError("Output escapes the writing directory")
            info = self.native(path).stat()
            if not self.native(path).is_file() or info.st_nlink != 1 or info.st_size > MAX_SOURCE_BYTES:
                raise ValueError("Output must be a regular single-link file at most 128 MiB")
            digest = hashlib.sha256()
            with self.native(path).open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            identity = [str(root), relative, kind, item.get("document_id", "main")]
            key = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
            artifact_id = "host-output-" + hashlib.sha256((key + digest.hexdigest()).encode()).hexdigest()[:40]
            entries.append({"path": relative, "artifact_type": kind, "sha256": digest.hexdigest(),
                            "artifact_id": artifact_id, "key": key, "document_id": item.get("document_id", "main")})
        # Publish figures/sources first: they invalidate earlier PDF renders.
        entries.sort(key=lambda item: item["artifact_type"] in ("pdf", "docx", "tex"))
        view = self.snapshot()
        indexed = {item["artifact_id"]: item for item in view.get("artifacts", [])}
        pending = [item for item in entries if item["artifact_id"] not in indexed
                   or indexed[item["artifact_id"]].get("stale")]
        grant = next((g for g in view.get("material_grants", []) if g["grant_id"] == state["grant_id"]), None)
        if grant and Path(grant["uri"]).resolve() != root:
            raise ValueError("Saved output grant points at a different directory")
        if pending and grant is None:
            view = self.command("paperspine_authorize_materials", view, {"replace": False, "grants": [{
                "grant_id": state["grant_id"], "uri": str(root), "scope": "read_only",
                "include_paths": [item["path"] for item in entries]}]})
        ids = []
        for item in entries:
            indexed = {artifact["artifact_id"]: artifact for artifact in view.get("artifacts", [])}
            existing = indexed.get(item["artifact_id"])
            if existing is None or existing.get("stale"):
                payload = {key: item[key] for key in ("artifact_id", "artifact_type", "sha256", "document_id")}
                payload.update(stage=stage, source={"grant_id": state["grant_id"], "relative_path": item["path"]})
                previous = state["published"].get(item["key"])
                if previous and previous != item["artifact_id"] and previous in indexed:
                    payload["supersedes_artifact_ids"] = [previous]
                view = self.command("paperspine_publish_artifact", view, payload)
                existing = next((a for a in view.get("artifacts", []) if a["artifact_id"] == item["artifact_id"]), None)
            if not existing or existing.get("stale") or existing.get("sha256") != item["sha256"]:
                raise ValueError("Published artifact read-back does not match the requested bytes")
            ids.append(item["artifact_id"])
            self.completed = list(ids)
            state["published"][item["key"]] = item["artifact_id"]
            self.save(state)
        milestone = {"stage": stage, "summary": summary, "artifact_ids": ids}
        last = (view.get("milestones") or [{}])[-1]
        if any(last.get(key) != value for key, value in milestone.items()) or view.get("stage") != stage:
            view = self.command("paperspine_commit_milestone", view, milestone)
        view = self.snapshot()
        last = (view.get("milestones") or [{}])[-1]
        indexed = {a["artifact_id"]: a for a in view.get("artifacts", [])}
        if (view.get("stage") != stage or any(last.get(key) != value for key, value in milestone.items())
                or any(not indexed.get(item["artifact_id"]) or indexed[item["artifact_id"]].get("stale")
                       or indexed[item["artifact_id"]].get("sha256") != item["sha256"] for item in entries)):
            raise ValueError("Checkpoint read-back differs; read the same task before retrying")
        return {"status": "SYNCED", "task_id": self.task_id, "task_version": view["task_version"],
                "writing_directory": str(root), **milestone,
                "pending_decisions": [d for d in view.get("decisions", []) if d.get("status") == "pending"]}


def run(args, root, client):
    binding = client.resolve_binding(args, root)
    profile = client.selected_profile(args)
    def rpc(name, arguments):
        job = {"binding": binding, "operation": "call", "name": name,
               "arguments": arguments, "timeout": args.timeout_seconds}
        reply = client._run_public_job(args, root, job)
        client._forward_stderr(reply.stderr)
        payload = json.loads(reply.stdout)
        if reply.returncode or payload.get("error"):
            if isinstance(payload.get("error"), dict):
                raise CommandFailure(payload["error"])
            raise RuntimeError(json.dumps(payload, ensure_ascii=False))
        return payload
    sync = Checkpoint(profile, args.task_id, binding, rpc)
    try:
        if args.host_command == "bind-output":
            result = sync.bind(args.writing_dir)
        else:
            raw = sys.stdin.read() if args.manifest == "-" else sync.native(Path(args.manifest).resolve()).read_text(encoding="utf-8-sig")
            manifest = json.loads(raw)
            if not isinstance(manifest, dict):
                raise ValueError("Manifest must be a JSON object")
            result = sync.sync(manifest)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "task_id": args.task_id, "error": str(exc),
                          "completed_artifact_ids": sync.completed, "automatic_retry": False,
                          "next_action": "Read this same task and rerun the checkpoint after fixing the reported failure."},
                         ensure_ascii=False, indent=2))
        return 1
