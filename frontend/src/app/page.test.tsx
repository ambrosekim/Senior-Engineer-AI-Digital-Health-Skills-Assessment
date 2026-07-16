import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import HomePage from "./page";

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
});

describe("HomePage", () => {
  it("shows a loading placeholder before the fetch resolves", () => {
    (fetch as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}));

    render(<HomePage />);

    expect(screen.getByText("Loading...")).toBeInTheDocument();
  });

  it("renders the HTML returned by the backend home route", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      text: async () => "<h1>Last Mile Health Assessment</h1>",
    });

    render(<HomePage />);

    expect(await screen.findByRole("heading", { name: "Last Mile Health Assessment" })).toBeInTheDocument();
  });

  it("shows a failure message when the backend is unreachable", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockRejectedValue(new Error("connection refused"));

    render(<HomePage />);

    expect(await screen.findByText("Failed to load home page.")).toBeInTheDocument();
  });
});
