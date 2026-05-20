import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { CommandPalette } from "./CommandPalette";
import type { PaletteCommand } from "./commandPaletteModel";

const commands: PaletteCommand[] = [
  {
    id: "open-setup",
    title: "Open Setup",
    section: "Navigation",
    description: "Open project selection and setup.",
    keywords: ["setup", "project"],
    routesTo: "Setup",
  },
  {
    id: "start-automation",
    title: "Start automation",
    section: "Automation",
    description: "Start the scheduler.",
    keywords: ["start"],
    dangerous: true,
    disabledReason: "Safety check before starting.",
  },
];

describe("CommandPalette", () => {
  it("renders accessible dialog, close control, command list, and live status", () => {
    const html = renderToStaticMarkup(
      <CommandPalette
        commands={commands}
        error="Command failed."
        message="Command started."
        onClose={() => undefined}
        onExecute={() => undefined}
      />,
    );

    expect(html).toContain('role="dialog"');
    expect(html).toContain('aria-modal="true"');
    expect(html).toContain('aria-label="Search commands"');
    expect(html).toContain('title="Close command palette"');
    expect(html).toContain('role="listbox"');
    expect(html).toContain('role="option"');
    expect(html).toContain('aria-live="polite"');
    expect(html).toContain("Safety check before starting.");
  });
});
