import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import UploadPage from "./page";

function pdfFile(name = "policy.pdf", sizeBytes = 1024) {
  const content = new Uint8Array(sizeBytes).fill(1);
  return new File([content], name, { type: "application/pdf" });
}

// applyAccept: false — the component enforces its own PDF/size validation in
// JS, so tests need to be able to select a non-matching file to exercise it
// (a real browser's file picker would otherwise pre-filter by `accept`).
function setupUser() {
  return userEvent.setup({ applyAccept: false });
}

async function selectFile(user: ReturnType<typeof setupUser>, file: File) {
  const input = document.querySelector<HTMLInputElement>('input[type="file"]');
  if (!input) throw new Error("file input not found");
  await user.upload(input, file);
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
});

describe("UploadPage", () => {
  it("renders the upload form in its idle state", () => {
    render(<UploadPage />);

    expect(screen.getByRole("heading", { name: "Upload a PDF" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Upload" })).toBeEnabled();
  });

  it("shows an error when submitting without choosing a file", async () => {
    const user = setupUser();
    render(<UploadPage />);

    await user.click(screen.getByRole("button", { name: "Upload" }));

    expect(await screen.findByText("Please choose a PDF file first.")).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("rejects a non-PDF file client-side without calling the API", async () => {
    const user = setupUser();
    render(<UploadPage />);
    const notAPdf = new File(["hello"], "notes.txt", { type: "text/plain" });

    await selectFile(user, notAPdf);
    await user.click(screen.getByRole("button", { name: "Upload" }));

    expect(await screen.findByText("Only PDF files are supported.")).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("rejects an oversized PDF client-side without calling the API", async () => {
    const user = setupUser();
    render(<UploadPage />);
    const tooBig = pdfFile("big.pdf", 21 * 1024 * 1024);

    await selectFile(user, tooBig);
    await user.click(screen.getByRole("button", { name: "Upload" }));

    expect(await screen.findByText(/too large/i)).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("shows a loading state and then the result on a successful upload", async () => {
    let resolveFetch: (value: unknown) => void = () => {};
    (fetch as ReturnType<typeof vi.fn>).mockReturnValue(
      new Promise((resolve) => {
        resolveFetch = resolve;
      })
    );

    const user = setupUser();
    render(<UploadPage />);
    await selectFile(user, pdfFile());
    await user.click(screen.getByRole("button", { name: "Upload" }));

    expect(await screen.findByRole("button", { name: "Uploading..." })).toBeDisabled();

    resolveFetch({
      ok: true,
      json: async () => ({
        document_id: "abc-123",
        filename: "policy.pdf",
        page_count: 3,
        chunk_count: 7,
        status: "ready",
        duplicate: false,
      }),
    });

    expect(await screen.findByText("Document uploaded and processed successfully.")).toBeInTheDocument();
    expect(screen.getByText("Filename: policy.pdf")).toBeInTheDocument();
    expect(screen.getByText("Chunks: 7")).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("/documents/upload"),
      expect.objectContaining({ method: "POST" })
    );
  });

  it("shows a distinct message for a duplicate upload", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => ({
        document_id: "abc-123",
        filename: "policy.pdf",
        page_count: 3,
        chunk_count: 7,
        status: "ready",
        duplicate: true,
      }),
    });

    const user = setupUser();
    render(<UploadPage />);
    await selectFile(user, pdfFile());
    await user.click(screen.getByRole("button", { name: "Upload" }));

    expect(await screen.findByText("This document was already uploaded previously.")).toBeInTheDocument();
  });

  it("shows the backend's error detail when the upload fails", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: false,
      status: 415,
      json: async () => ({ detail: "Only PDF files are accepted" }),
    });

    const user = setupUser();
    render(<UploadPage />);
    await selectFile(user, pdfFile());
    await user.click(screen.getByRole("button", { name: "Upload" }));

    expect(await screen.findByText("Only PDF files are accepted")).toBeInTheDocument();
  });

  it("shows a generic error message when the network request itself fails", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockRejectedValue(new Error("network down"));

    const user = setupUser();
    render(<UploadPage />);
    await selectFile(user, pdfFile());
    await user.click(screen.getByRole("button", { name: "Upload" }));

    await waitFor(() => {
      expect(screen.getByText("network down")).toBeInTheDocument();
    });
  });
});
