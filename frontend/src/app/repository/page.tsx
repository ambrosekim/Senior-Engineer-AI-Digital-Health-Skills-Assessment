"use client";

import { useEffect, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:6100";

interface DocumentListItem {
  document_id: string;
  filename: string;
  page_count: number;
  chunk_count: number;
  status: string;
  created_at: string;
}

type LoadState =
  | { status: "loading" }
  | { status: "success"; documents: DocumentListItem[] }
  | { status: "error"; message: string };

function formatDate(value: string): string {
  return new Date(value).toLocaleString();
}

function StatusBadge({ status }: { status: string }) {
  return <span className={`status-badge status-${status}`}>{status}</span>;
}

export default function RepositoryPage() {
  const [state, setState] = useState<LoadState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setState({ status: "loading" });
      try {
        const response = await fetch(`${API_BASE}/documents`);
        if (!response.ok) {
          throw new Error(`Failed to load documents (${response.status}).`);
        }
        const documents: DocumentListItem[] = await response.json();
        if (!cancelled) {
          setState({ status: "success", documents });
        }
      } catch (err) {
        if (!cancelled) {
          setState({
            status: "error",
            message: err instanceof Error ? err.message : "Failed to load documents.",
          });
        }
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="home-bg">
      <div className="repository-card">
        <h1>Document Repository</h1>
        <p>All documents uploaded to the RAG knowledge base.</p>

        {state.status === "loading" && <p>Loading documents...</p>}

        {state.status === "error" && <p className="upload-message-error">{state.message}</p>}

        {state.status === "success" && state.documents.length === 0 && (
          <p>No documents have been uploaded yet.</p>
        )}

        {state.status === "success" && state.documents.length > 0 && (
          <div className="repository-table-wrapper">
            <table className="repository-table">
              <thead>
                <tr>
                  <th>Filename</th>
                  <th>Pages</th>
                  <th>Chunks</th>
                  <th>Status</th>
                  <th>Uploaded</th>
                </tr>
              </thead>
              <tbody>
                {state.documents.map((doc) => (
                  <tr key={doc.document_id}>
                    <td>{doc.filename}</td>
                    <td>{doc.page_count}</td>
                    <td>{doc.chunk_count}</td>
                    <td>
                      <StatusBadge status={doc.status} />
                    </td>
                    <td>{formatDate(doc.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
