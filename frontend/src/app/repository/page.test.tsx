import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import RepositoryPage from "./page";

const SAMPLE_DOCUMENTS = [
  {
    document_id: "doc-1",
    filename: "kenya-health-policy.pdf",
    page_count: 44,
    chunk_count: 112,
    status: "ready",
    created_at: "2026-07-15T20:17:27.939253Z",
  },
  {
    document_id: "doc-2",
    filename: "tele-mental-health-guidelines.pdf",
    page_count: 33,
    chunk_count: 72,
    status: "processing",
    created_at: "2026-07-16T00:10:42.639111Z",
  },
];

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
});

describe("RepositoryPage", () => {
  it("shows a loading state before the fetch resolves", () => {
    (fetch as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}));

    render(<RepositoryPage />);

    expect(screen.getByText("Loading documents...")).toBeInTheDocument();
  });

  it("shows an empty-state message when there are no documents", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => [],
    });

    render(<RepositoryPage />);

    expect(await screen.findByText("No documents have been uploaded yet.")).toBeInTheDocument();
  });

  it("renders a row per document with filename, counts, and status", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => SAMPLE_DOCUMENTS,
    });

    render(<RepositoryPage />);

    expect(await screen.findByText("kenya-health-policy.pdf")).toBeInTheDocument();
    expect(screen.getByText("tele-mental-health-guidelines.pdf")).toBeInTheDocument();
    expect(screen.getByText("112")).toBeInTheDocument();
    expect(screen.getByText("ready")).toBeInTheDocument();
    expect(screen.getByText("processing")).toBeInTheDocument();
  });

  it("shows an error message when the response is not ok", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: false,
      status: 500,
    });

    render(<RepositoryPage />);

    expect(await screen.findByText("Failed to load documents (500).")).toBeInTheDocument();
  });

  it("shows an error message when the fetch itself throws", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockRejectedValue(new Error("offline"));

    render(<RepositoryPage />);

    expect(await screen.findByText("offline")).toBeInTheDocument();
  });
});
