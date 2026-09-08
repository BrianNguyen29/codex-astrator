# Artifact-specific clarifications

These optional notes can accompany the orchestration instructions when a task
creates a document artifact.

- Render the latest document, slide, or PDF output and inspect the affected
  views when the environment permits; source inspection alone is not visual
  verification.
- Preserve source files and interactivity by default. Do not flatten PDF forms
  or overwrite a reference artifact without explicit authorization.
- Keep generated previews and scratch output in an explicit temporary
  directory. Remove only temporary files created by the task after checks;
  retain requested intermediates and recovery backups.
- If rendering is unavailable after safe alternatives, label the artifact
  usable but visually unverified and state the missing check.
