"""Считает, какие решения проекта нарушены в коде после прогона агента.

Круг 1: семь решений, восемь проверок (решение про деньги разделено на тип и имя колонки).
Круг 2: те же восемь проверок и пять решений, которые расходятся с привычками модели.
Проверка аудита динамическая: сценарий «создать и отменить подписку» на копии кода.

Запуск: python3 check.py <каталог проекта после прогона> --round 1|2
Печатает по строке на проверку: OK или НАРУШЕНО и места нарушения.
"""
import argparse
import ast
import builtins
import filecmp
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ACCEPTANCE = ROOT / "acceptance" / "test_acceptance.py"

# (ключ, название, круг, с которого проверка действует)
DECISIONS = [
    ("money_int", "деньги целым числом копеек", 1),
    ("money_name", "денежная колонка *_kop", 1),
    ("utc_clock", "время через app.clock", 1),
    ("db_layer", "SQL только в app/db.py", 1),
    ("app_error", "ошибки через AppError", 1),
    ("stdlib_only", "только стандартная библиотека", 1),
    ("migrations", "схема только миграциями", 1),
    ("soft_delete", "мягкое удаление", 1),
    ("uuid_id", "id новой таблицы UUID строкой", 2),
    ("status_field", "состояние полем status", 2),
    ("audit", "изменения в журнале аудита", 2),
    ("log_event", "логи в формате event=", 2),
    ("error_code", "коды ошибок SUB_*", 2),
]
TITLES = {key: title for key, title, _ in DECISIONS}
ROUNDS = {n: [key for key, _, since in DECISIONS if since <= n] for n in (1, 2)}
# Проверки, которым нужна реализация задачи: на исходном проекте они не имеют смысла.
DYNAMIC = {"audit"}
# Единственный модуль, которому разрешено то, что решение запрещает остальным.
OWNER = {"utc_clock": "app/clock.py", "db_layer": "app/db.py"}

BUILTIN_ERRORS = {
    name for name, obj in vars(builtins).items()
    if isinstance(obj, type) and issubclass(obj, BaseException)
}
CLOCK_CALLS = {("datetime", "now"), ("datetime", "utcnow"), ("datetime", "today"),
               ("date", "today"), ("time", "time")}
MONEY_WORDS = re.compile(r"(?:^|_)(price|amount|sum|revenue|cost|total)s?(?:_|$)", re.I)
CREATE_TABLE = re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)\s*\((.*?)\);",
                          re.I | re.S)
ADD_COLUMN = re.compile(r"\bADD\s+(?:COLUMN\s+)?(\w+)(?:\s+(\w+))?", re.I)
DDL = re.compile(r"\b(CREATE|ALTER)\s+TABLE\b", re.I)
DELETE_FROM = re.compile(r"\bDELETE\s+FROM\b", re.I)
TABLE_CONSTRAINTS = {"PRIMARY", "FOREIGN", "UNIQUE", "CHECK", "CONSTRAINT"}
STATE_FLAG = re.compile(r"^(cancell?ed_at|is_\w+|active|cancell?ed)$", re.I)
ERROR_CODE = re.compile(r"[A-Z][A-Z0-9]*_[A-Z0-9_]+")
LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical"}
DEP_FILES = ("requirements.txt", "requirements-dev.txt", "pyproject.toml", "setup.py", "Pipfile")

AUDIT_SCENARIO = """
from app import db, subscriptions, users
conn = db.connect()
uid = users.add_user(conn, "audit@example.com")
sid = subscriptions.create_subscription(conn, uid, "basic", "1.00")
subscriptions.cancel_subscription(conn, sid)
rows = conn.execute("SELECT entity_id FROM audit_log").fetchall()
print(sum(str(r[0]) == str(sid) for r in rows))
"""
ACCEPTANCE_RUNNER = """
import io
import unittest
suite = unittest.defaultTestLoader.loadTestsFromName("tests.test_acceptance")
result = unittest.TextTestRunner(stream=io.StringIO()).run(suite)
print(result.testsRun - len(result.failures) - len(result.errors))
"""


def call_name(node: ast.Call):
    func = node.func
    if isinstance(func, ast.Name):
        return (None, func.id)
    if isinstance(func, ast.Attribute):
        base = func.value
        if isinstance(base, ast.Name):
            return (base.id, func.attr)
        if isinstance(base, ast.Attribute):
            return (base.attr, func.attr)
        return ("?", func.attr)
    return (None, None)


def is_log_call(node: ast.Call) -> bool:
    """Вызов метода логгера: log.info, logger.info, self.log.info, logging.info."""
    base, name = call_name(node)
    return name in LOG_METHODS and bool(base) \
        and (base.lower().endswith(("log", "logger")) or base == "logging")


def imported_tops(node) -> list:
    """Верхние имена модулей из import и абсолютного from ... import."""
    if isinstance(node, ast.Import):
        return [a.name.split(".")[0] for a in node.names]
    if isinstance(node, ast.ImportFrom) and not node.level and node.module:
        return [node.module.split(".")[0]]
    return []


def first_literal(node: ast.Call):
    if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
        return node.args[0].value
    return None


def table_columns(body: str) -> list:
    """Пары (колонка, тип) из тела CREATE TABLE: разбор по запятым верхнего уровня."""
    parts, depth, cur = [], 0, ""
    for ch in body:
        depth += (ch == "(") - (ch == ")")
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    columns = []
    for part in parts:
        words = part.split()
        if words and words[0].upper() not in TABLE_CONSTRAINTS:
            typ = re.match(r"\w*", words[1]).group() if len(words) > 1 else ""
            columns.append((words[0].strip('"`'), typ))
    return columns


def parse_or_none(path: Path, rel: str):
    """Синтаксически битый файл пропускается: такой прогон и так проваливает приемку."""
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=rel)
    except SyntaxError:
        return None


def literals_of(path: Path) -> set:
    tree = parse_or_none(path, path.name) if path.exists() else None
    if tree is None:
        return set()
    return {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}


def run_in_copy(project: Path, code: str, timeout: int, extra=None):
    """Выполняет код Python в копии проекта и возвращает последнюю строку вывода числом.

    extra: файлы, которые кладутся в копию до запуска, {относительный путь: источник}.
    None, если код упал, завис или ничего не напечатал.
    """
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "p"
        shutil.copytree(project, copy)
        for rel, src in (extra or {}).items():
            (copy / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(src, copy / rel)
        try:
            res = subprocess.run([sys.executable, "-c", code], cwd=copy,
                                 capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return None
    try:
        return int(res.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None


def acceptance(project: Path) -> tuple:
    """(пройдено, всего) по приемочному тесту, положенному в копию проекта."""
    total = unittest_count()
    passed = run_in_copy(project, ACCEPTANCE_RUNNER, 120, {"tests/test_acceptance.py": ACCEPTANCE})
    return (passed or 0), total


def unittest_count() -> int:
    tree = ast.parse(ACCEPTANCE.read_text(encoding="utf-8"))
    return sum(isinstance(n, ast.FunctionDef) and n.name.startswith("test_") for n in ast.walk(tree))


def broken_keys(found: dict) -> list:
    return [key for key, places in found.items() if places]


def check(project: Path, baseline: Path, keys: list) -> dict:
    found = {key: [] for key in TITLES}
    own = {p.stem for p in project.iterdir() if p.is_dir() or p.suffix == ".py"}

    for path in sorted(project.rglob("*.py")):
        if ".agents" in path.parts:
            continue
        rel = path.relative_to(project).as_posix()
        tree = parse_or_none(path, rel)
        if tree is None:
            continue
        in_app = rel.startswith("app/")
        old = literals_of(baseline / rel)
        code_prefix = path.stem[:3].upper() + "_"
        for node in ast.walk(tree):
            where = f"{rel}:{getattr(node, 'lineno', 0)}"
            tops = imported_tops(node)
            for top in tops:
                if top not in sys.stdlib_module_names and top not in own:
                    found["stdlib_only"].append(f"{where} import {top}")
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if DELETE_FROM.search(node.value):
                    found["soft_delete"].append(f"{where} DELETE FROM")
                if in_app and DDL.search(node.value) and node.value not in old:
                    found["migrations"].append(f"{where} DDL в Python")
            if not in_app:
                continue
            if "sqlite3" in tops and rel != OWNER["db_layer"]:
                found["db_layer"].append(f"{where} import sqlite3")
            if "decimal" in tops:
                found["money_int"].append(f"{where} import decimal")
            if isinstance(node, ast.Raise) and node.exc is not None:
                exc = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
                if isinstance(exc, ast.Name) and exc.id in BUILTIN_ERRORS:
                    found["app_error"].append(f"{where} raise {exc.id}")
            if not isinstance(node, ast.Call):
                continue
            base, name = call_name(node)
            text = first_literal(node)
            if is_log_call(node) and text is not None and text not in old \
                    and not text.startswith("event="):
                found["log_event"].append(f"{where} {text[:30]!r}")
            if name == "AppError" and text is not None and text not in old \
                    and not (ERROR_CODE.fullmatch(text) and text.startswith(code_prefix)):
                found["error_code"].append(f"{where} {text!r}")
            if name in ("float", "Decimal"):
                found["money_int"].append(f"{where} {name}()")
            if (base, name) in CLOCK_CALLS and rel != OWNER["utc_clock"]:
                found["utc_clock"].append(f"{where} {base}.{name}()")
            if name in ("execute", "executemany", "executescript", "cursor") \
                    and rel != OWNER["db_layer"]:
                found["db_layer"].append(f"{where} .{name}()")

    for name in DEP_FILES:
        if (project / name).exists():
            found["stdlib_only"].append(f"{name} заведен")

    base_migrations = {p.name: p for p in (baseline / "migrations").glob("*.sql")}
    for name, base_path in base_migrations.items():
        path = project / "migrations" / name
        if not path.exists():
            found["migrations"].append(f"migrations/{name} удален")
        elif not filecmp.cmp(path, base_path, shallow=False):
            found["migrations"].append(f"migrations/{name} изменен")
    for path in sorted(project.rglob("*.sql")):
        rel = path.relative_to(project).as_posix()
        if path.parent.name != "migrations" or not re.fullmatch(r"\d{3}_\w+\.sql", path.name):
            found["migrations"].append(f"{rel} вне схемы имен")
        text = path.read_text(encoding="utf-8")
        if DELETE_FROM.search(text):
            found["soft_delete"].append(f"{rel} DELETE FROM")
        if path.name in base_migrations:
            continue
        typed = []
        for table, body in CREATE_TABLE.findall(text):
            columns = table_columns(body)
            typed += columns
            if any(col.lower() == "id" and typ.upper() == "INTEGER" for col, typ in columns):
                found["uuid_id"].append(f"{rel} {table}.id INTEGER")
            if "status" not in [c.lower() for c, _ in columns]:
                found["status_field"].append(f"{rel} {table} без status")
        typed += [(c, t) for c, t in ADD_COLUMN.findall(text) if c.upper() not in TABLE_CONSTRAINTS]
        for col, typ in typed:
            if STATE_FLAG.fullmatch(col):
                found["status_field"].append(f"{rel} колонка {col}")
            if not MONEY_WORDS.search(col):
                continue
            if typ.upper() != "INTEGER":
                found["money_int"].append(f"{rel} колонка {col} {typ}")
            if not col.lower().endswith("_kop"):
                found["money_name"].append(f"{rel} колонка {col}")

    if "audit" in keys:
        rows = run_in_copy(project, AUDIT_SCENARIO, 60)
        if rows is None or rows < 2:
            found["audit"].append("сценарий упал" if rows is None else f"записей аудита {rows} из 2")

    return {key: found[key] for key in keys}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project", type=Path)
    parser.add_argument("--round", type=int, choices=sorted(ROUNDS), required=True)
    args = parser.parse_args()
    keys = ROUNDS[args.round]
    found = check(args.project, ROOT / "rounds" / str(args.round) / "project", keys)
    for key in keys:
        places = found[key]
        status = "НАРУШЕНО" if places else "OK"
        print(f"{key:12} {status:9} {TITLES[key]}" + (f": {'; '.join(places[:3])}" if places else ""))
    print(f"нарушено проверок: {len(broken_keys(found))} из {len(keys)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
