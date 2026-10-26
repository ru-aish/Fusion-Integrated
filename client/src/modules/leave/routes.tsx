import { lazy } from "react";
import { type RouteObject } from "react-router-dom";

const BalancesPage = lazy(() => import("./pages/BalancesPage"));
const RequestsPage = lazy(() => import("./pages/RequestsPage"));
const InboxPage = lazy(() => import("./pages/InboxPage"));
const ConfigurationPage = lazy(() => import("./pages/ConfigurationPage"));

export const routes: RouteObject[] = [
  { path: "balances", element: <BalancesPage /> },
  { path: "requests", element: <RequestsPage /> },
  { path: "inbox", element: <InboxPage /> },
  { path: "configuration", element: <ConfigurationPage /> },
];
