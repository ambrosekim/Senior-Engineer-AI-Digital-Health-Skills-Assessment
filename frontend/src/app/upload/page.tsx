"use client";

import { useRef, useState, type FormEvent } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:6100";
// Keep in sync with the backend's MAX_UPLOAD_SIZE_BYTES (settings.max_upload_size_bytes).
const MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024;

interface UploadResult {
  document_id: string;
  filename: string;
  page_count: number;
  chunk_count: number;
  status: string;
  duplicate?: boolean;
}

type UploadState =
  | { status: "idle" }
  | { status: "uploading" }
  | { status: "success"; result: UploadResult }
  | { status: "error"; message: string };

function validateFile(file: File): string | null {
  const hasPdfType = file.type === "application/pdf";
  const hasPdfExtension = file.name.toLowerCase().endsWith(".pdf");
  if (!hasPdfType && !hasPdfExtension) {
    return "Only PDF files are supported.";
  }
  if (file.size === 0) {
    return "The selected file is empty.";
  }
  if (file.size > MAX_FILE_SIZE_BYTES) {
    return `File is too large. Maximum size is ${MAX_FILE_SIZE_BYTES / (1024 * 1024)}MB.`;
  }
  return null;
}

export default function UploadPage() {
  const [state, setState] = useState<UploadState>({ status: "idle" });
  const inputRef = useRef<HTMLInputElement>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const file = inputRef.current?.files?.[0];
    if (!file) {
      setState({ status: "error", message: "Please choose a PDF file first." });
      return;
    }

    const validationError = validateFile(file);
    if (validationError) {
      setState({ status: "error", message: validationError });
      return;
    }

    const formData = new FormData();
    formData.append("file", file);

    setState({ status: "uploading" });
    try {
      const response = await fetch(`${API_BASE}/documents/upload`, {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail || `Upload failed (${response.status}).`);
      }

      const result: UploadResult = await response.json();
      setState({ status: "success", result });
      if (inputRef.current) {
        inputRef.current.value = "";
      }
    } catch (err) {
      setState({
        status: "error",
        message: err instanceof Error ? err.message : "Upload failed. Please try again.",
      });
    }
  }

  const isUploading = state.status === "uploading";

  return (
    <div className="home-bg">
      <div className="upload-card">
        <h1>Upload a PDF</h1>
        <p>
          Upload a PDF document to ingest it into the RAG knowledge base. Only PDF files
          under {MAX_FILE_SIZE_BYTES / (1024 * 1024)}MB are accepted.
        </p>

        <form className="upload-form" onSubmit={handleSubmit}>
          <input
            ref={inputRef}
            type="file"
            accept="application/pdf,.pdf"
            disabled={isUploading}
          />
          <button type="submit" className="upload-button" disabled={isUploading}>
            {isUploading ? "Uploading..." : "Upload"}
          </button>
        </form>

        {state.status === "error" && <p className="upload-message-error">{state.message}</p>}

        {state.status === "success" && (
          <div className="upload-result">
            <p>
              {state.result.duplicate
                ? "This document was already uploaded previously."
                : "Document uploaded and processed successfully."}
            </p>
            <ul>
              <li>Filename: {state.result.filename}</li>
              <li>Pages: {state.result.page_count}</li>
              <li>Chunks: {state.result.chunk_count}</li>
              <li>Status: {state.result.status}</li>
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}
