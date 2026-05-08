import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import App, { viewRequiresTarget } from "./App";

describe("App shell", () => {
  it("renders the preserved sidebar routes in order", () => {
    const html = renderToStaticMarkup(<App />);
    const labels = ["Home", "Brief", "Run", "Observatory", "Inbox", "Review", "Advanced"];
    const positions = labels.map((label) => html.indexOf(`>${label}</span>`));

    expect(positions.every((position) => position > -1)).toBe(true);
    expect(positions).toEqual([...positions].sort((a, b) => a - b));
  });

  it("renders useful no-target startup state without raw UNKNOWN", () => {
    const html = renderToStaticMarkup(<App />);

    expect(html).toContain("Choose a project to begin");
    expect(html).toContain("Choose Project Folder");
    expect(html).toContain("Safety is checked after a target is selected");
    expect(html).toContain("Choose project");
    expect(html).not.toContain("UNKNOWN");
  });

  it("renders page-specific placeholders when target-required pages are selected without a project", () => {
    const html = renderToStaticMarkup(<App initialView="Run" />);

    expect(html).toContain("Open a project before running automation");
    expect(html).toContain("Choose Project Folder");
    expect(html).toContain("Continue Brief");
    expect(html).not.toContain("Choose a project to begin");
    expect(viewRequiresTarget("Run")).toBe(true);
    expect(viewRequiresTarget("Brief")).toBe(false);
  });

  it("exposes project switch and close actions from the project chip menu", () => {
    const html = renderToStaticMarkup(<App initialProjectMenuOpen />);

    expect(html).toContain("Switch Project...");
    expect(html).toContain("Create New Project");
    expect(html).toContain("Close Project");
  });
});
