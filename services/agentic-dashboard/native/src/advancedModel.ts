import type { RegisteredFile } from "./api/backend";

export type AdvancedEditorModel = {
  dirty: boolean;
  statusLabel: string;
  canSave: boolean;
  canDiscard: boolean;
  canValidate: boolean;
  canOpen: boolean;
  canReveal: boolean;
};

export function buildAdvancedEditorModel(input: {
  selectedFile?: RegisteredFile | null;
  editorContent: string;
  savedContent: string;
  busy?: string;
  loading?: boolean;
}): AdvancedEditorModel {
  const selected = input.selectedFile ?? null;
  const busy = Boolean(input.busy) || input.loading === true;
  const dirty = input.editorContent !== input.savedContent;
  const exists = selected?.exists === true;
  const editable = selected?.editable !== false;

  return {
    dirty,
    statusLabel: dirty ? "Unsaved changes" : "Saved",
    canSave: Boolean(selected) && editable && dirty && !busy,
    canDiscard: dirty && !busy,
    canValidate: Boolean(selected) && !busy,
    canOpen: exists && !busy,
    canReveal: exists && !busy,
  };
}
