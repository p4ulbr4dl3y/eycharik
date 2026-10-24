import { expect, test } from "@playwright/test";

import { HR, RECRUITER, nav, signIn, signedInAs } from "./session";

test.describe("a recruiter's session", () => {
  test("logs in with a token and leaves no token in the page", async ({ page }) => {
    await signIn(page, RECRUITER);

    const storage = await page.evaluate(() => ({
      local: JSON.stringify(localStorage),
      session: JSON.stringify(sessionStorage),
      hash: window.location.hash,
    }));
    expect(storage.local).not.toContain(RECRUITER);
    expect(storage.session).not.toContain(RECRUITER);
    expect(storage.hash).not.toContain(RECRUITER);

    const cookies = await page.context().cookies();
    const session = cookies.find((cookie) => cookie.name === "onboarding_session");
    expect(session?.httpOnly).toBe(true);
  });

  test("keeps the filter in the address and survives a reload", async ({ page }) => {
    await signedInAs(page, RECRUITER);
    await nav(page, "Вопросы");
    await page.getByRole("tab", { name: "Отвеченные" }).click();

    await expect(page).toHaveURL(/#\/questions\?status=answered/);
    await page.reload();

    await expect(page.getByRole("tab", { name: "Отвеченные" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  test("searches the cohort on the server and pages it", async ({ page }) => {
    await signedInAs(page, RECRUITER);
    await nav(page, "Сотрудники");
    await page.getByRole("searchbox", { name: "Поиск по сотрудникам" }).fill("кузнецов");

    await expect(page.getByText("Пётр Кузнецов")).toBeVisible();
    await expect(page).toHaveURL(/q=/);
    await expect(page.getByText("Анна Смирнова")).toHaveCount(0);
  });

  test("claims a question and keeps the claim in the filter", async ({ page }) => {
    await signedInAs(page, RECRUITER);
    await nav(page, "Вопросы");
    await page.getByRole("button", { name: "Забрать себе" }).first().click();

    await expect(page.getByText("Ваш вопрос").first()).toBeVisible();

    await page.getByRole("tab", { name: "Мои" }).click();
    await expect(page).toHaveURL(/owner=me/);
    await expect(page.getByText("Ваш вопрос").first()).toBeVisible();
  });

  test("offers no knowledge upload to a role without the capability", async ({ page }) => {
    await signedInAs(page, RECRUITER);
    await nav(page, "Знания");

    await expect(page.getByRole("heading", { name: "Что ассистент знает" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Загрузить файл" })).toHaveCount(0);
  });

  test("opens a run card and shows its timeline", async ({ page }) => {
    await signedInAs(page, RECRUITER);
    await nav(page, "Сотрудники");
    await page.getByRole("button", { name: /Анна Смирнова/ }).click();

    await expect(page.getByRole("heading", { name: "Анна Смирнова" })).toBeVisible();
    await expect(page.getByText("Хронология")).toBeVisible();
    await expect(page.getByRole("button", { name: "Офбордить" })).toHaveCount(0);
  });
});

test.describe("an hr session", () => {
  test("opens a document, edits it, and waits for re-indexing", async ({ page }) => {
    await signIn(page, HR);
    await nav(page, "Знания");
    await page.getByRole("button", { name: /Открыть документ Отпуска и отгулы/ }).click();

    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog.getByText("hr/leave-policy")).toBeVisible();

    await dialog.getByRole("button", { name: "Редактировать" }).click();
    const editor = dialog.getByLabel("Markdown с frontmatter");
    const source = await editor.inputValue();
    await editor.fill(`${source}\n\nПроверка редактирования.`);
    await dialog.getByRole("button", { name: "Сохранить и переиндексировать" }).click();

    await expect(dialog.getByText("Документ обновлён и переиндексирован.")).toBeVisible({
      timeout: 10_000,
    });
  });

  test("offboards in two steps and comes back to the list", async ({ page }) => {
    await signIn(page, HR);
    await nav(page, "Сотрудники");
    await page.getByRole("button", { name: /Мария Волкова/ }).click();

    await page.getByRole("button", { name: "Офбордить" }).click();
    await expect(page.getByText(/Переписка Мария Волкова будет удалена сразу/)).toBeVisible();
    await page.getByRole("button", { name: "Да, офбордить" }).click();

    await expect(page.getByText(/офборджен: удалено 2 вопроса, 14 сообщений/)).toBeVisible();
    await page.getByRole("button", { name: "К списку сотрудников" }).click();
    await expect(page.getByRole("heading", { name: "Новые сотрудники" })).toBeVisible();
  });

  test("signs out and returns to the gate", async ({ page }) => {
    await signIn(page, HR);
    await page.getByRole("button", { name: "Выйти" }).click();

    await expect(page.getByLabel("Токен доступа")).toBeVisible();
    const cookies = await page.context().cookies();
    expect(cookies.find((cookie) => cookie.name === "onboarding_session")?.value ?? "").toBe("");
  });
});
