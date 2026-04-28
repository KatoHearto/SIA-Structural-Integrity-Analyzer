import React from "react";
import ReactDOM from "react-dom/client";

export function AppShell() {
    return <main>Hello multi-language world</main>;
}

ReactDOM.createRoot(document.getElementById("root")!).render(<AppShell />);
