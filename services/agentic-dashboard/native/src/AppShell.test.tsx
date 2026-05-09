import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import App, { viewRequiresTarget } from "./App";

describe("App shell", () => {
  it("renders the preserved sidebar routes in order", () => {
    const html = renderToStaticMarkup(<App />);
    const labels = ["Home", "Brief", "Run", "Observatory", "Inbox", "Review", "Advanced"];
    const positions = labels.map((label) => html.indexOf(`data-sidebar-view="${label}"`));

    expect(positions.every((position) => position > -1)).toBe(true);
    expect(positions).toEqual([...positions].sort((a, b) => a - b));
  });

  it("renders useful no-target startup state without raw UNKNOWN", () => {
    const html = renderToStaticMarkup(<App />);

    expect(html).toContain("Choose a project");
    expect(html).toContain("Choose project");
    expect(html).toContain("No target selected");
    expect(html).toContain("Choose project");
    expect(html).not.toContain("UNKNOWN");
  });

  it("renders page-specific placeholders when target-required pages are selected without a project", () => {
    const html = renderToStaticMarkup(<App initialView="Run" />);

    expect(html).toContain("Select a project to run jobs");
    expect(html).toContain("Choose project");
    expect(html).toContain("Open setup");
    expect(html).not.toContain("Choose a project to begin");
    expect(viewRequiresTarget("Run")).toBe(true);
    expect(viewRequiresTarget("Brief")).toBe(false);
  });

  it("exposes project switch and close actions from the project chip menu", () => {
    const html = renderToStaticMarkup(<App initialProjectMenuOpen />);

    expect(html).toContain("Switch project...");
    expect(html).toContain("New project");
    expect(html).toContain("Close Project");
  });
});
