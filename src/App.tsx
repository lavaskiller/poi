import { Routes, Route, Outlet } from "react-router-dom";
import Sidebar from "./components/Sidebar";
import Home from "./pages/Home";
import NewRun from "./pages/NewRun";
import Results from "./pages/Results";
import CaseInspector from "./pages/CaseInspector";
import Compare from "./pages/Compare";
import Placeholder from "./pages/Placeholder";

function Layout() {
  return (
    <div style={{ display: "flex", alignItems: "stretch", height: "100%" }}>
      <Sidebar />
      <Outlet />
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Home />} />
        <Route path="new-run" element={<NewRun />} />
        <Route path="results" element={<Results />} />
        <Route path="case" element={<CaseInspector />} />
        <Route path="compare" element={<Compare />} />
        <Route path="datasets" element={<Placeholder title="Datasets" />} />
        <Route path="jobs" element={<Placeholder title="Jobs" />} />
      </Route>
    </Routes>
  );
}
