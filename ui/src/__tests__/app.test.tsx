import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import App from "../App";

describe("App", () => {
  it("renders the chat placeholder", () => {
    render(<App />);
    expect(screen.getByText(/lexbot chat placeholder/i)).toBeInTheDocument();
  });
});