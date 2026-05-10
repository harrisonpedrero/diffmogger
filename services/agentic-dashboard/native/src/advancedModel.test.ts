import { describe, expect, it } from "vitest";
import type { RegisteredFile } from "./api/backend";
import { buildAdvancedEditorModel } from "./advancedModel";

const editableFile: RegisteredFile = {
  key: "state.dashboard",
  label: "Dashboard state",
  rel_path: ".agentic/dashboard_state.json",
  group: "state",
  category: "Core state",
  path: "/tmp/project/.agentic/dashboard_state.json",
  exists: true,
  editable: true,
  size_bytes: 12,
  modified_at: "2026-05-06T12:00:00+00:00",
};

describe("buildAdvancedEditorModel", () => {
  it("enables save and discard only after the editor is dirty", () => {
    const clean = buildAdvancedEditorModel({
      selectedFile: editableFile,
      editorContent: "{}\n",
      savedContent: "{}\n",
    });
    const dirty = buildAdvancedEditorModel({
      selectedFile: editableFile,
      editorContent: "{\"changed\": true}\n",
      savedContent: "{}\n",
    });

    expect(clean.statusLabel).toBe("Saved");
    expect(clean.canSave).toBe(false);
    expect(clean.canDiscard).toBe(false);
    expect(dirty.statusLabel).toBe("Unsaved changes");
    expect(dirty.canSave).toBe(true);
    expect(dirty.canDiscard).toBe(true);
  });

  it("keeps read-only generated artifacts from being saved", () => {
    const readOnlyFile = { ...editableFile, key: "review.observatory_html", editable: false };
    const model = buildAdvancedEditorModel({
      selectedFile: readOnlyFile,
      editorContent: "<html>changed</html>",
      savedContent: "<html></html>",
    });

    expect(model.dirty).toBe(true);
    expect(model.canSave).toBe(false);
    expect(model.canOpen).toBe(true);
    expect(model.canReveal).toBe(true);
  });
});
