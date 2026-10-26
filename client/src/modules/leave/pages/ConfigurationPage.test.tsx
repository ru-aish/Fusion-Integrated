import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { http } from "../../../lib/http";
import ConfigurationPage from "./ConfigurationPage";

describe("leave configuration", () => {
  it("shows existing HR configuration and submits a validated profile form", async () => {
    vi.spyOn(http, "get").mockImplementation(async (url) => {
      if (url === "/leave/profiles/") return { data: { results: [{ employee_id: "1001", unit_head_id: "2001" }] } };
      if (url === "/leave/calendar/") return { data: { results: [] } };
      if (url === "/leave/offline-records/" || url === "/leave/sla/") return { data: [] };
      if (url === "/leave/year-end/") return { data: { runs: [], accounts: [] } };
      return { data: [{ cl_annual: 8, rh_annual: 2 }] };
    });
    vi.spyOn(http, "post").mockResolvedValue({ data: {} });
    const query = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={query}>{(<ConfigurationPage />) as ReactNode}</QueryClientProvider>);
    expect(await screen.findByText(/1001: Unit Head 2001/)).toBeInTheDocument();
    fireEvent.change(screen.getAllByLabelText("Employee ID")[0]!, { target: { value: "1002" } });
    fireEvent.change(screen.getByLabelText("Unit Head ID"), { target: { value: "2002" } });
    fireEvent.change(screen.getByLabelText("Final authority ID"), { target: { value: "3002" } });
    fireEvent.click(screen.getByRole("button", { name: "Save profile" }));
    await waitFor(() => expect(http.post).toHaveBeenCalledWith("/leave/profiles/", expect.objectContaining({
      employee_id: "1002", unit_head_id: "2002", sanctioning_authority_id: "3002",
    })));
  });
});
