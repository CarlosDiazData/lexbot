import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import SettingsModal from "../SettingsModal";
import ChatView from "../ChatView";

describe("SettingsModal", () => {
  it("does not render when isOpen is false", () => {
    render(
      <SettingsModal
        isOpen={false}
        onClose={vi.fn()}
        theme="system"
        onThemeChange={vi.fn()}
      />
    );
    expect(screen.queryByTestId("settings-modal")).not.toBeInTheDocument();
  });

  it("renders when isOpen is true with all theme options", () => {
    render(
      <SettingsModal
        isOpen={true}
        onClose={vi.fn()}
        theme="dark"
        onThemeChange={vi.fn()}
      />
    );
    expect(screen.getByTestId("settings-modal")).toBeInTheDocument();
    expect(screen.getByText(/settings/i)).toBeInTheDocument();
    expect(screen.getByTestId("theme-option-light")).toBeInTheDocument();
    expect(screen.getByTestId("theme-option-dark")).toBeInTheDocument();
    expect(screen.getByTestId("theme-option-system")).toBeInTheDocument();
    expect(screen.getByText(/gemini-2.5-flash-lite/i)).toBeInTheDocument();
  });

  it("triggers onThemeChange when a theme option is clicked", async () => {
    const onThemeChange = vi.fn();
    const user = userEvent.setup();

    render(
      <SettingsModal
        isOpen={true}
        onClose={vi.fn()}
        theme="light"
        onThemeChange={onThemeChange}
      />
    );

    await user.click(screen.getByTestId("theme-option-dark"));
    expect(onThemeChange).toHaveBeenCalledWith("dark");
  });

  it("calls onClose when the close button or backdrop is clicked", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();

    render(
      <SettingsModal
        isOpen={true}
        onClose={onClose}
        theme="system"
        onThemeChange={vi.fn()}
      />
    );

    await user.click(screen.getByRole("button", { name: /close settings/i }));
    expect(onClose).toHaveBeenCalledTimes(1);

    await user.click(screen.getByTestId("settings-backdrop"));
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("closes when Escape key is pressed", () => {
    const onClose = vi.fn();
    render(
      <SettingsModal
        isOpen={true}
        onClose={onClose}
        theme="system"
        onThemeChange={vi.fn()}
      />
    );

    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe("ChatView Settings Integration", () => {
  it("opens settings modal when clicking the settings button in header", async () => {
    const user = userEvent.setup();
    render(<ChatView />);

    expect(screen.queryByTestId("settings-modal")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /open settings/i }));
    expect(screen.getByTestId("settings-modal")).toBeInTheDocument();
  });
});
