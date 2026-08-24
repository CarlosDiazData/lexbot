import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import App from "../App";

describe("App", () => {
  it("renders the chat view with a message input", () => {
    render(<App />);
    expect(screen.getByLabelText(/message/i)).toBeInTheDocument();
  });
});