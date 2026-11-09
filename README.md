# agent-rules-memory-demo

[![check](https://github.com/sproshchaev/agent-rules-memory-demo/actions/workflows/check.yml/badge.svg)](https://github.com/sproshchaev/agent-rules-memory-demo/actions/workflows/check.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**Сергей Прощаев**

[![Website](https://img.shields.io/badge/prosoft.pages.dev-blue?logo=googlechrome&logoColor=white)](https://prosoft.pages.dev)
[![LinkedIn](https://img.shields.io/badge/LinkedIn-sproshchaev-0A66C2)](https://www.linkedin.com/in/sproshchaev/)
[![Habr](https://img.shields.io/badge/Habr-sproshchaev-65A3BE?logo=habr&logoColor=white)](https://habr.com/ru/users/sproshchaev/)

---

## 1. Что это

Эксперимент к статье на Хабре
"[Правила проекта для агента: AGENTS.md и skills, чтобы вайб-проект не забывал решения между сессиями](https://habr.com/ru/companies/otus/articles/1101906/)".

Агент получает одну и ту же задачу в небольшом проекте, каждый раз в новой сессии с нуля. Вопрос: какие решения команды он соблюдает сам, глядя на код, а какие только тогда, когда они записаны в `AGENTS.md` или в skill.

## 2. Что внутри

```text
rounds/1/project/   проект, который меняет агент: пользователи, SQLite, миграции
rounds/1/task.md    задача: подписки и отчет по выручке
rounds/1/variants/  правила: agents_md (все в AGENTS.md), skill (короткий AGENTS.md и skill)
rounds/1/reference/ эталонное решение без нарушений
rounds/1/runs/      код после каждой сессии агента и ее сводка (session.txt)
rounds/2/           то же для второго круга: плюс журнал аудита и пять новых решений
acceptance/         приемочный тест задачи, агент его не видит
check.py            проверки решений по коду после сессии
selftest.py         проверка самих проверок на подложенных нарушениях
summarize.py        сводка по сохраненным прогонам и сверка с expected.txt
run_experiment.sh   новые сессии агента (нужен Codex CLI и вход в него)
run.sh              пересчет без живой модели, его же запускает CI
```

## 3. Требования

`python3` 3.10 или новее, сторонние пакеты не используются. Для пересчета результатов модель не нужна: код всех 18 сессий лежит в `rounds/*/runs/`.

Для новых сессий нужен Codex CLI (проверено на 0.166.0) с выполненным входом.

## 4. Быстрый старт

```bash
git clone https://github.com/sproshchaev/agent-rules-memory-demo.git
cd agent-rules-memory-demo
./run.sh
```

`run.sh` сначала проверяет проверяльщик: исходный проект и эталон дают ноль нарушений, эталон проходит приемку, каждое подложенное нарушение ловится только своей проверкой. Затем для каждой сессии заново считает нарушения и прогоняет приемочный тест, пишет `results.md` и сверяет его с `expected.txt`. При расхождении код выхода 1.

## 5. Как ставили эксперимент

- **Агент:** Codex CLI 0.166.0, модель `gpt-6.1-sol`, `codex exec` в режиме `workspace-write`, 09.11.2026.
- **Изоляция:** каждая сессия идет во временном каталоге с временными `CODEX_HOME` и `HOME`. Глобальный `AGENTS.md` и личные skills пользователя в сессию не попадают, из настоящего `CODEX_HOME` берется только файл входа. Пробная сессия подтвердила: агент видит `AGENTS.md` проекта, skill `project-decisions` и системные skills самого Codex.
- **Варианты:** без правил, все решения в `AGENTS.md`, короткий `AGENTS.md` со ссылкой на skill `project-decisions` и решения в `SKILL.md`. По три сессии на вариант в каждом круге.
- **Круг 1:** семь решений. Три видны в коде (время через `app.clock`, SQL в `db.py`, ошибки через `AppError`), четыре записаны только в правилах.
- **Круг 2:** те же семь и еще пять, которые расходятся с привычками модели: UUID вместо автонумерации, состояние полем `status`, журнал аудита, логи в формате `event=`, коды ошибок вида `SUB_NOT_FOUND`.
- **Проверка:** `check.py` разбирает код через `ast` и SQL миграций. Аудит проверяется по поведению: сценарий "создать и отменить подписку" на копии кода, затем записи в `audit_log`.

## 6. Результаты

Полная таблица по каждой сессии лежит в `results.md`. Приемочный тест прошли все 18 сессий, 5 из 5.

| Вариант | Круг 1, нарушено из 8 | Круг 2, нарушено из 13 |
|---|---:|---:|
| без правил | 2, 2, 2 | 5, 5, 5 |
| AGENTS.md | 0, 0, 0 | 0, 0, 0 |
| AGENTS.md + skill | 0, 0, 0 | 0, 0, 0 |

Что нарушает агент без правил во всех шести сессиях:

- Кладет SQL прямо в `subscriptions.py`, хотя рядом `users.py` ходит в базу через `db.py`.
- Называет колонку `price_kopecks` вместо принятого `price_kop`. Сами деньги он хранит целыми копейками, без `float`.

И во втором круге еще в трех из трех:

- Заводит `cancelled_at` вместо поля `status`.
- Не пишет журнал аудита, хотя `db.add_audit` в проекте есть.
- Пишет коды ошибок в старом стиле `bad_price`.

Skill агент открыл во всех шести сессиях варианта со skill: `AGENTS.md` прямо на него указывает. Признак в `session.txt` ставится, если в одной из команд агента есть строка `SKILL.md`. Полный поток событий сессий не сохранялся, поэтому сами команды этих 18 сессий посмотреть нельзя. Новые прогоны пишут команду в поле `skill_command`.

## 7. Ограничения

- Одна модель, один агент, одна задача и по три сессии на вариант. Это демонстрация механики. Долю нарушений для моделей вообще отсюда не вывести.
- Решение про UUID подсказала сама задача второго круга: сигнатура требует id строкой, и модель берет `uuid4` без правил. Эта проверка ничего не измеряет.
- Без правил агент не пишет логов в новом модуле вовсе, поэтому проверка формата `event=` проходит на пустом месте.
- Проверку про деньги разделили на тип и имя колонки после чтения первых прогонов: изначальная общая проверка засчитывала нарушение за одно только имя колонки.
- Skill вызывался потому, что `AGENTS.md` прямо на него ссылается. Без такой ссылки skill может не загрузиться вовсе, этот вариант здесь не проверялся.

## 8. Лицензия

[MIT](LICENSE)

## 9. Полезные ссылки

- Статья на Хабре: https://habr.com/ru/companies/otus/articles/1101906/
- Gloaguen T. и др. Evaluating AGENTS.md: Are Repository-Level Context Files Helpful for Coding Agents? https://arxiv.org/abs/2602.11988
- Vercel. AGENTS.md outperforms skills in our agent evals, 27.01.2026: https://vercel.com/blog/agents-md-outperforms-skills-in-our-agent-evals
- Спецификация AGENTS.md: https://agents.md
- Спецификация Agent Skills: https://agentskills.io
