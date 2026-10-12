import React from "react";
import { afterEach, expect, it, vi } from "vitest";
import { LocaleSwitcher } from "./LocaleSwitcher";

const replace = vi.hoisted(() => vi.fn());
vi.mock("next-intl", () => ({ useLocale: () => "zh" }));
vi.mock("@/i18n/navigation", () => ({
  usePathname: () => "/evolution/prepare",
  useRouter: () => ({ replace }),
}));

afterEach(() => {
  vi.unstubAllGlobals();
  replace.mockReset();
});

it("preserves the experiment target, repeated query values and anchor on locale change", () => {
  vi.stubGlobal("React", React);
  vi.stubGlobal("window", {
    location: {
      search: "?targetKind=paper_runner&targetId=fixture-id&tag=a&tag=b",
      hash: "#coverage",
    },
  });
  const buttons = LocaleSwitcher().props.children;
  buttons[0].props.onClick();
  expect(replace).toHaveBeenCalledWith(
    "/evolution/prepare?targetKind=paper_runner&targetId=fixture-id&tag=a&tag=b#coverage",
    { locale: "en" },
  );
});
