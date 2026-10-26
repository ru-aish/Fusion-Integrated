import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { http } from "../../../lib/http";
import RequestsPage from "./RequestsPage";

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>{(<RequestsPage />) as ReactNode}</QueryClientProvider>,
  );
}

describe("leave request form", () => {
  it("shows COL evidence input and submits the reference with the application", async () => {
    vi.spyOn(http, "get").mockResolvedValue({ data: { results: [] } });
    vi.spyOn(http, "post").mockResolvedValue({ data: {} });
    renderPage();

    fireEvent.change(screen.getByLabelText("Leave type"), { target: { value: "COL" } });
    expect(screen.getByLabelText("Medical evidence reference (if required)")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("From"), { target: { value: "2026-11-02" } });
    fireEvent.change(screen.getByLabelText("To"), { target: { value: "2026-11-02" } });
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "Medical leave" } });
    fireEvent.change(screen.getByLabelText("Medical evidence reference (if required)"), {
      target: { value: "MED-REF-2026-11" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Submit request" }));

    await waitFor(() => expect(http.post).toHaveBeenCalledWith("/leave/requests/", {
      leave_type: "COL",
      start_date: "2026-11-02",
      end_date: "2026-11-02",
      reason: "Medical leave",
      half_day: "none",
      station_leave: false,
      station_leave_details: "",
      medical_evidence_reference: "MED-REF-2026-11",
      substitute_id: "",
    }));
  });
});
